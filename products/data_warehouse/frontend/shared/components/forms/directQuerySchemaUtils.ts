import { groupBy } from 'lib/utils'

import { ExternalDataSourceSyncSchema } from '~/types'

export function splitDirectQueryTableName(
    table: string,
    fallbackSchema?: string | null
): { schemaName: string; tableName: string } {
    const firstDotIndex = table.indexOf('.')

    if (firstDotIndex === -1) {
        const normalizedFallbackSchema = fallbackSchema?.trim()
        return {
            schemaName: normalizedFallbackSchema || 'Tables',
            tableName: table,
        }
    }

    return {
        schemaName: table.slice(0, firstDotIndex),
        tableName: table.slice(firstDotIndex + 1),
    }
}

export function groupDirectQueryTablesBySchema(
    schemas: ExternalDataSourceSyncSchema[],
    fallbackSchema?: string | null
): { schemaName: string; tables: ExternalDataSourceSyncSchema[] }[] {
    return Object.entries(
        groupBy(schemas, (schema) => splitDirectQueryTableName(schema.table, fallbackSchema).schemaName)
    )
        .sort(([schemaA], [schemaB]) => schemaA.localeCompare(schemaB))
        .map(([schemaName, tables]) => ({ schemaName, tables }))
}

export function getDefaultExpandedDirectQuerySchemaKeys(
    groupedSchemas: { schemaName: string; tables: ExternalDataSourceSyncSchema[] }[]
): string[] {
    return groupedSchemas.map((group) => group.schemaName)
}
