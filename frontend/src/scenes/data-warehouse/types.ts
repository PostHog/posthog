import { DatabaseSchemaDataWarehouseTable } from '~/queries/schema/schema-general'

export type DataWarehouseTableForInsight = DatabaseSchemaDataWarehouseTable & {
    id_field?: string
    timestamp_field?: string
    distinct_id_field?: string
}
