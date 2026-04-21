import { ExternalDataSource, ExternalDataSourceSchema } from '~/types'

export interface DirectPostgresProjectionColumn {
    name: string
    data_type: string
    is_nullable: boolean
}

export interface DirectPostgresProjectionCustomField {
    name: string
    expression: string
}

export interface DirectPostgresProjectionForeignKey {
    column: string
    target_table: string
    target_column: string
}

export interface DirectPostgresProjectionSchemaMetadata {
    columns: DirectPostgresProjectionColumn[]
    foreign_keys?: DirectPostgresProjectionForeignKey[]
    source_catalog?: string | null
    source_schema?: string | null
    source_table_name?: string | null
    query_name?: string | null
    custom_fields?: DirectPostgresProjectionCustomField[]
}

export interface ExternalDataSourceSchemaWithProjectionMetadata extends ExternalDataSourceSchema {
    schema_metadata?: DirectPostgresProjectionSchemaMetadata | null
    source_schema_metadata?: DirectPostgresProjectionSchemaMetadata | null
}

export interface ExternalDataSourceWithProjectionMetadata extends ExternalDataSource {
    schemas: ExternalDataSourceSchemaWithProjectionMetadata[]
}

export interface DirectPostgresProjectionTableConfig {
    source_name: string
    source_catalog?: string | null
    source_schema?: string | null
    source_table_name?: string | null
    enabled: boolean
    query_name: string
    removed_fields: string[]
    custom_fields: DirectPostgresProjectionCustomField[]
    foreign_keys: DirectPostgresProjectionForeignKey[]
}

export interface DirectPostgresProjectionRevisionConfig {
    tables?: DirectPostgresProjectionTableConfig[]
}

export interface DirectPostgresProjectionRevision {
    id: string
    version: number
    config: DirectPostgresProjectionRevisionConfig
    is_active: boolean
    created_at: string
    created_by: string | null
}

export function getRawProjectionSchemaMetadata(
    schema: ExternalDataSourceSchemaWithProjectionMetadata
): DirectPostgresProjectionSchemaMetadata | null {
    return schema.source_schema_metadata ?? schema.schema_metadata ?? null
}
