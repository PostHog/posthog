from .fragments import MONEY_V2_FRAGMENT

SHOPIFY_PAYMENTS_BALANCE_TRANSACTIONS_QUERY = f"""
query PaginatedShopifyPaymentsBalanceTransactions($n: Int!, $cursor: String) {{
	shopifyPaymentsAccount {{
		balanceTransactions(first: $n, after: $cursor) {{
			nodes {{
				adjustmentsOrders(first: 250) {{
                    amount {MONEY_V2_FRAGMENT}
                    fees {MONEY_V2_FRAGMENT}
                    name
                    net {MONEY_V2_FRAGMENT}
                    orderTransactionId
				}}
				amount {MONEY_V2_FRAGMENT}
				associatedOrder {{
					id
					name
				}}
				associatedPayout {{
					id
                    status
				}}
				fee {MONEY_V2_FRAGMENT}
				id
				net {MONEY_V2_FRAGMENT}
				sourceOrderTransactionId
				sourceType
				test
				transactionDate
				type
			}}
			pageInfo {{
				hasNextPage
				endCursor
			}}
		}}
	}}
}}"""
