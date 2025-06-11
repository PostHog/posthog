type MarketingAnalyticsSchemaField = {
    type: string[]
    required: boolean
}

export const MARKETING_ANALYTICS_SCHEMA: Record<string, MarketingAnalyticsSchemaField> = {
    campaign_name: { type: ['string'], required: true },
    total_cost: { type: ['float', 'integer'], required: true },
    clicks: { type: ['integer', 'number', 'float'], required: false },
    impressions: { type: ['integer', 'number', 'float'], required: false },
    date: { type: ['datetime', 'date', 'string'], required: true }, // self managed sources dates are not converted to date type
    source_name: { type: ['string'], required: false },
    utm_campaign_name: { type: ['string'], required: false },
    utm_source_name: { type: ['string'], required: false },
}

export type MarketingAnalyticsSchema = keyof typeof MARKETING_ANALYTICS_SCHEMA

export const MARKETING_ANALYTICS_CONVERSION_GOAL_SCHEMA: Record<string, MarketingAnalyticsSchemaField> = {
    utm_campaign_name: { type: ['string'], required: true },
    utm_source_name: { type: ['string'], required: true },
}

export type ConversionGoalSchema = keyof typeof MARKETING_ANALYTICS_CONVERSION_GOAL_SCHEMA
