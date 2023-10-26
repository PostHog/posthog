import { DatabaseSchemaQueryResponseField, HogQLQuery } from '~/queries/schema'

export interface DatabaseTableListRow {
    name: string
    columns: DatabaseSchemaQueryResponseField[]
}

export interface DataWarehouseSceneRow extends DatabaseTableListRow {
    id: string
    url_pattern?: string
    format?: string
    query?: HogQLQuery
}
