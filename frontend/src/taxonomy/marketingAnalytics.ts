export const UTM_CAMPAIGN_NAME_SCHEMA_FIELD = 'utm_campaign_name' as const
export const UTM_SOURCE_NAME_SCHEMA_FIELD = 'utm_source_name' as const
export const DISTINCT_ID_FIELD_SCHEMA_FIELD = 'distinct_id_field' as const
export const TIMESTAMP_FIELD_SCHEMA_FIELD = 'timestamp_field' as const

// KLUDGE: This should ideally be a union of the strings above,
// however the backend is pretty borked and assumes it's a string everywhere
// and migrating away from this is not trivial
export type ConversionGoalSchema = string
type ConversionGoalSchemaType = { type: string[]; required: boolean; isCurrency: boolean }

export const MARKETING_ANALYTICS_CONVERSION_GOAL_SCHEMA: Record<ConversionGoalSchema, ConversionGoalSchemaType> = {
    // UTM fields are required for conversion goals to properly track attribution
    [UTM_CAMPAIGN_NAME_SCHEMA_FIELD]: { type: ['string'], required: true, isCurrency: false },
    [UTM_SOURCE_NAME_SCHEMA_FIELD]: { type: ['string'], required: true, isCurrency: false },
    [TIMESTAMP_FIELD_SCHEMA_FIELD]: { type: ['datetime', 'date', 'string'], required: true, isCurrency: false },
    [DISTINCT_ID_FIELD_SCHEMA_FIELD]: { type: ['string'], required: false, isCurrency: false },
}
