type MarketingAnalyticsSchemaField = {
    type: string[]
    required: boolean
}

export const MARKETING_ANALYTICS_SCHEMA: Record<string, MarketingAnalyticsSchemaField> = {
    campaign_name: { type: ['string'], required: true },
    total_cost: { type: ['float', 'integer'], required: true },
    clicks: { type: ['integer', 'number', 'float'], required: true },
    impressions: { type: ['integer', 'number', 'float'], required: true },
    date: { type: ['datetime', 'date'], required: true },
    source_name: { type: ['string'], required: false },
}
