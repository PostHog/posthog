import { groupBy } from 'lib/utils'

export function splitQualifiedTableName(
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

export function groupTablesBySchema<T>(
    schemas: T[],
    getTableName: (item: T) => string,
    fallbackSchema?: string | null
): { schemaName: string; tables: T[] }[] {
    return Object.entries(
        groupBy(schemas, (schema) => splitQualifiedTableName(getTableName(schema), fallbackSchema).schemaName)
    )
        .sort(([schemaA], [schemaB]) => schemaA.localeCompare(schemaB))
        .map(([schemaName, tables]) => ({ schemaName, tables }))
}

export function getDefaultExpandedSchemaKeys<T>(groupedSchemas: { schemaName: string; tables: T[] }[]): string[] {
    return groupedSchemas.map((group) => group.schemaName)
}
