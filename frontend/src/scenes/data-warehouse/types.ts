import { DatabaseSchemaQueryResponseField, HogQLQuery } from '~/queries/schema'
import { ExternalDataStripeSource } from '~/types'

export interface DatabaseTableListRow {
    name: string
    columns: DatabaseSchemaQueryResponseField[]
    external_data_source?: ExternalDataStripeSource
}

export interface DataWarehouseSceneRow extends DatabaseTableListRow {
    id: string
    url_pattern?: string
    format?: string
    query?: HogQLQuery
}
