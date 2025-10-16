from .fragments import MONEY_V2_FRAGMENT

SHOPIFY_PAYMENTS_ACCOUNT_BALANCE_TRANSACTIONS_QUERY = f"""
query PaginatedShopifyPaymentsAccountBalanceTransactions($pageSize: Int!, $cursor: String) {{
	shopifyPaymentsAccount {{
		balanceTransactions(first: $pageSize, after: $cursor) {{
			nodes {{
				adjustmentsOrders {{
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
