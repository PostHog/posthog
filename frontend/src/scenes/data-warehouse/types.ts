import { DatabaseSchemaQueryResponseField, HogQLQuery } from '~/queries/schema'
import { ExternalDataStripeSource, SimpleExternalDataSourceSchema } from '~/types'

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
