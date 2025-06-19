type MarketingAnalyticsSchemaField = {
    type: string[]
    required: boolean
}

export const UTM_CAMPAIGN_NAME_SCHEMA_FIELD = 'utm_campaign_name'
export const UTM_SOURCE_NAME_SCHEMA_FIELD = 'utm_source_name'

export const MARKETING_ANALYTICS_SCHEMA: Record<string, MarketingAnalyticsSchemaField> = {
    campaign_name: { type: ['string'], required: true },
    clicks: { type: ['integer', 'number', 'float'], required: false },
    currency: { type: ['string'], required: false },
    date: { type: ['datetime', 'date', 'string'], required: true }, // self managed sources dates are not converted to date type
    impressions: { type: ['integer', 'number', 'float'], required: false },
    source_name: { type: ['string'], required: false },
    total_cost: { type: ['float', 'integer'], required: true },
    [UTM_CAMPAIGN_NAME_SCHEMA_FIELD]: { type: ['string'], required: false },
    [UTM_SOURCE_NAME_SCHEMA_FIELD]: { type: ['string'], required: false },
}

export type MarketingAnalyticsSchema = keyof typeof MARKETING_ANALYTICS_SCHEMA

export const MARKETING_ANALYTICS_CONVERSION_GOAL_SCHEMA: Record<string, MarketingAnalyticsSchemaField> = {
    [UTM_CAMPAIGN_NAME_SCHEMA_FIELD]: { type: ['string'], required: true },
    [UTM_SOURCE_NAME_SCHEMA_FIELD]: { type: ['string'], required: true },
}

export type ConversionGoalSchema = keyof typeof MARKETING_ANALYTICS_CONVERSION_GOAL_SCHEMA
