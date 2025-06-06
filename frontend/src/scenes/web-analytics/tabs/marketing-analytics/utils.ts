type MarketingAnalyticsSchemaField = {
    type: string[]
    required: boolean
    default?: string
}

export type MarketingAnalyticsSchema = keyof typeof MARKETING_ANALYTICS_SCHEMA

export const MARKETING_ANALYTICS_SCHEMA: Record<string, MarketingAnalyticsSchemaField> = {
    campaign_name: { type: ['string'], required: true },
    total_cost: { type: ['float', 'integer'], required: true },
    clicks: { type: ['integer', 'number', 'float'], required: false },
    impressions: { type: ['integer', 'number', 'float'], required: false },
    date: { type: ['datetime', 'date', 'string'], required: true }, // self managed sources dates are not converted to date type
    source_name: { type: ['string'], required: false },
}

export type SourceMap = Record<MarketingAnalyticsSchema, string | undefined>
