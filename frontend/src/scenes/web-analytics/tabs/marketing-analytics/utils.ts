type MarketingAnalyticsSchemaField = {
    type: string[]
    required: boolean
}

export type MarketingAnalyticsSchema = keyof typeof MARKETING_ANALYTICS_SCHEMA

export const MARKETING_ANALYTICS_SCHEMA: Record<string, MarketingAnalyticsSchemaField> = {
    campaign_name: { type: ['string'], required: true },
    total_cost: { type: ['float', 'integer'], required: true },
    clicks: { type: ['integer', 'number', 'float'], required: true },
    impressions: { type: ['integer', 'number', 'float'], required: true },
    date: { type: ['datetime', 'date'], required: true },
    source_name: { type: ['string'], required: false },
}

export type SourceMap = Record<MarketingAnalyticsSchema, string | undefined>
