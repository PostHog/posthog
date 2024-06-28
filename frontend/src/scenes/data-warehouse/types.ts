import { DatabaseSchemaDataWarehouseTable } from '~/queries/schema'

export enum DataWarehouseSceneTab {
    Tables = 'tables',
    Joins = 'joins',
}

export type DataWarehouseTableForInsight = DatabaseSchemaDataWarehouseTable & {
    id_field?: string
    timestamp_field?: string
    distinct_id_field?: string
}
