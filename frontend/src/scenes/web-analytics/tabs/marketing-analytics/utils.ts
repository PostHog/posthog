import { MarketingAnalyticsSchemaField } from '~/queries/schema/schema-general'

export const UTM_CAMPAIGN_NAME_SCHEMA_FIELD = 'utm_campaign_name'
export const UTM_SOURCE_NAME_SCHEMA_FIELD = 'utm_source_name'
export const DISTINCT_ID_FIELD_SCHEMA_FIELD = 'distinct_id_field'
export const TIMESTAMP_FIELD_SCHEMA_FIELD = 'timestamp_field'

export const MARKETING_ANALYTICS_CONVERSION_GOAL_SCHEMA: Record<string, MarketingAnalyticsSchemaField> = {
    // UTM fields are required for conversion goals to properly track attribution
    [UTM_CAMPAIGN_NAME_SCHEMA_FIELD]: { type: ['string'], required: true },
    [UTM_SOURCE_NAME_SCHEMA_FIELD]: { type: ['string'], required: true },
    [TIMESTAMP_FIELD_SCHEMA_FIELD]: { type: ['datetime', 'date', 'string'], required: true },
    [DISTINCT_ID_FIELD_SCHEMA_FIELD]: { type: ['string'], required: false },
}

export type ConversionGoalSchema = keyof typeof MARKETING_ANALYTICS_CONVERSION_GOAL_SCHEMA
