import { DatabaseSchemaDataWarehouseTable } from '~/queries/schema/schema-general'

import { SourceConfigResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

export type DataWarehouseTableForInsight = DatabaseSchemaDataWarehouseTable & {
    id_field?: string
    timestamp_field?: string
    distinct_id_field?: string
    aggregation_target_field?: string
}

/**
 * One entry of a source config's field list. Orval inlines this union in every place the
 * schema uses it, so there is no generated name to import; derive it from the response type
 * instead of restating the member list.
 */
export type SourceFieldConfig = SourceConfigResponseApi['fields'][number]
