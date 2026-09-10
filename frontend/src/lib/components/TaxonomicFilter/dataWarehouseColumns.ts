import { DatabaseSchemaField, DatabaseSchemaTable, DatabaseSerializedFieldType } from '~/queries/schema/schema-general'

/** Fields that stand for another table instead of a value, so they are never a selectable column. */
export const HIDDEN_FIELD_TYPES: DatabaseSerializedFieldType[] = [
    'lazy_table',
    'virtual_table',
    'view',
    'materialized_view',
]

/**
 * Columns the given data warehouse tables offer as a breakdown or a property.
 * The join field itself is always dropped, because it resolves to a table and not to a value.
 *
 * `includeJoinedColumns` also emits the columns of every joined table one level deep, as a dotted
 * path (`campaigns.name`). Only a caller whose query backend splits that path back into a field
 * chain may turn it on. Trends splits it in `get_properties_chain`, but the funnel backend reads
 * the whole dotted string as one column name, so the query cannot resolve the field.
 */
export function dataWarehouseColumnsWithJoins(
    tableNames: string[],
    tablesMap: Record<string, DatabaseSchemaTable>,
    includeJoinedColumns: boolean
): DatabaseSchemaField[] {
    const columns: DatabaseSchemaField[] = []

    for (const tableName of tableNames) {
        for (const field of Object.values(tablesMap[tableName]?.fields ?? {})) {
            if (!HIDDEN_FIELD_TYPES.includes(field.type)) {
                columns.push(field)
                continue
            }
            if (!includeJoinedColumns || !field.table) {
                continue
            }
            for (const joinedField of Object.values(tablesMap[field.table]?.fields ?? {})) {
                if (HIDDEN_FIELD_TYPES.includes(joinedField.type)) {
                    continue
                }
                columns.push({
                    ...joinedField,
                    name: `${field.name}.${joinedField.name}`,
                    hogql_value: `${field.hogql_value}.${joinedField.hogql_value}`,
                })
            }
        }
    }

    return columns
}
