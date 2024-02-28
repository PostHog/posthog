import { DatabaseSchemaQueryResponseField, HogQLQuery } from '~/queries/schema'
import {
    DataWarehouseSavedQuery,
    DataWarehouseTable,
    ExternalDataStripeSource,
    SimpleExternalDataSourceSchema,
} from '~/types'

export interface DatabaseTableListRow {
    name: string
    columns: DatabaseSchemaQueryResponseField[]
    external_data_source?: ExternalDataStripeSource
    external_schema?: SimpleExternalDataSourceSchema
}

export enum DataWarehouseRowType {
    ExternalTable = 'external_table',
    View = 'view',
    PostHogTable = 'posthog_table',
}
export interface DataWarehouseSceneRow extends DatabaseTableListRow {
    id: string
    type: DataWarehouseRowType
    url_pattern?: string
    format?: string
    query?: HogQLQuery
}

export interface DataWarehouseTableBaseType {
    id: string
    name: string
    type: DataWarehouseRowType
    columns: DatabaseSchemaQueryResponseField[]
}

export interface DataWarehousePostHogTableType extends DataWarehouseTableBaseType {
    type: DataWarehouseRowType.PostHogTable
    payload: DatabaseTableListRow
}

export interface DataWarehouseExternalTablType extends DataWarehouseTableBaseType {
    type: DataWarehouseRowType.ExternalTable
    payload: DataWarehouseTable
}

export interface DataWarehouseViewType extends DataWarehouseTableBaseType {
    type: DataWarehouseRowType.View
    payload: DataWarehouseSavedQuery
}

export type DataWarehouseTableType =
    | DataWarehousePostHogTableType
    | DataWarehouseExternalTablType
    | DataWarehouseViewType

export enum DataWarehouseSceneTab {
    Tables = 'tables',
    Joins = 'joins',
}
