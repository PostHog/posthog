import { ProductKey, QueryLogTags } from '~/queries/schema/schema-general'

export const CUSTOMER_ANALYTICS_DATA_COLLECTION_NODE_ID = 'customer-analytics'

export const CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS: QueryLogTags = {
    productKey: ProductKey.CUSTOMER_ANALYTICS,
}
