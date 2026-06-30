import { ProductKey, QueryLogTags } from '~/queries/schema/schema-general'

export const CUSTOMER_ANALYTICS_DATA_COLLECTION_NODE_ID = 'customer-analytics'

export const ACCOUNTS_HOGQL_DATA_NODE_KEY = 'customer-analytics-accounts-hogql'

// Overview-tile metrics load through their own data node so their (slower)
// aggregations never block the list rows from rendering.
export const ACCOUNTS_METRICS_DATA_NODE_KEY = 'customer-analytics-accounts-metrics'

export const CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS: QueryLogTags = {
    productKey: ProductKey.CUSTOMER_ANALYTICS,
}
