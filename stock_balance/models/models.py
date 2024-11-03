from odoo import api, fields, models


class StockQuantBalance(models.Model):
    _inherit = 'stock.quant'

    def turn_wdb(self):
        import wdb
        wdb.set_trace()

    @api.constrains('product_id')
    def check_product_id(self):
        pass

    def action_balance_qty(self):
        sqlscrpt_products = """
            WITH incoming AS (
                SELECT product_id, SUM(quantity)
                FROM stock_move_line
                WHERE location_dest_id = %s AND state = 'done'
                GROUP BY product_id
            ), outgoing AS (
                SELECT product_id, SUM(quantity)
                FROM stock_move_line
                WHERE location_id = %s AND state = 'done'
                GROUP BY product_id
            ), incomingvsoutgoing AS (
                SELECT incoming.product_id AS id, incoming.sum AS incoming, outgoing.sum AS outgoing
                FROM incoming
                JOIN outgoing ON incoming.product_id = outgoing.product_id
            ), comparison AS (
                SELECT id, SUM(incoming) AS quant_incoming, SUM(outgoing) AS quant_outgoing, 
                    SUM(incoming - outgoing) AS supposed_stock
                FROM incomingvsoutgoing
                GROUP BY id
            ), stock_qty AS (
                SELECT product_id, SUM(quantity) AS quant_stock_ontable
                FROM stock_quant
                WHERE location_id = %s
                GROUP BY product_id
            ), supposed_stock_vs_stock_on_table AS (
                SELECT id, quant_incoming, quant_outgoing, supposed_stock, quant_stock_ontable
                FROM comparison
                JOIN stock_qty ON comparison.id = stock_qty.product_id
            ), results AS (
                SELECT id, SUM(quant_incoming) AS quant_incoming, SUM(supposed_stock) AS supposed_stock, 
                    SUM(quant_outgoing) AS quant_outgoing, 
                    SUM(supposed_stock - quant_stock_ontable) AS difference, 
                    SUM(quant_stock_ontable) AS quant_stock_ontable
                FROM supposed_stock_vs_stock_on_table
                GROUP BY id
            ), results_w_code AS (
                SELECT results.id, results.quant_incoming, results.quant_outgoing, results.difference, 
                    supposed_stock, default_code, product_tmpl_id, quant_stock_ontable
                FROM results
                JOIN product_product ON results.id = product_product.id
            )
            SELECT results_w_code.id AS product_database_id, results_w_code.quant_incoming, 
                results_w_code.quant_outgoing, supposed_stock, results_w_code.quant_stock_ontable, 
                difference, product_template.name AS corrupted_product_name, 
                product_template.default_code AS corrupted_product_code
            FROM results_w_code
            JOIN product_template ON results_w_code.product_tmpl_id = product_template.id
            WHERE difference IS NOT NULL AND difference <> 0
            ORDER BY difference DESC;
        """

        sqlscrpt_moves = """
            SELECT product_id, location_id, location_dest_id, quantity, lot_id
            FROM stock_move_line
            WHERE state = 'done' AND product_id = %s 
            AND (location_id = %s OR location_dest_id = %s);
        """

        for loc in self.env['stock.location'].search([]):
            loc_id = loc.id
            self.env.cr.execute(sqlscrpt_products, (loc_id, loc_id, loc_id))
            prdcts = self.env.cr.dictfetchall()

            if prdcts:
                for prdct in prdcts:
                    prdct_id = prdct.get('product_database_id')

                    # Reset wrong quantities for the product in the location
                    self.search([
                        ('location_id', '=', loc_id),
                        ('product_id', '=', prdct_id)
                    ]).write({'quantity': 0})

                    # Fetch stock moves
                    self.env.cr.execute(sqlscrpt_moves, (prdct_id, loc_id, loc_id))
                    moves = self.env.cr.dictfetchall()

                    for move in moves:
                        lot_id = move['lot_id']
                        quantity = move['quantity']

                        # Adjust quantity based on source/destination location
                        if move['location_id'] == loc_id:
                            quantity *= -1

                        # Update or create the stock quant record
                        sqrcrd = self.search([
                            ('product_id', '=', prdct_id),
                            ('location_id', '=', loc_id),
                            ('lot_id', '=', lot_id)
                        ], limit=1)

                        if not sqrcrd:
                            self.create({
                                'product_id': prdct_id,
                                'location_id': loc_id,
                                'lot_id': lot_id,
                                'quantity': quantity
                            })
                        else:
                            sqrcrd.write({
                                'quantity': sqrcrd.quantity + quantity
                            })

        print('Balance done')
