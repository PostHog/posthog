import { DatabaseSchemaQueryResponseField } from '~/queries/schema'

export interface DatabaseSceneRow {
    name: string
    columns: DatabaseSchemaQueryResponseField[]
}

export interface DataWarehouseSceneRow extends DatabaseSceneRow {
    id: string
    url_pattern?: string
    format?: string
}
