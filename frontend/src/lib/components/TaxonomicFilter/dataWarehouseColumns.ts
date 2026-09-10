import { DatabaseSchemaField, DatabaseSchemaTable, DatabaseSerializedFieldType } from '~/queries/schema/schema-general'

/** Fields that stand for another table instead of a value, so they are never a selectable column. */
export const HIDDEN_FIELD_TYPES: DatabaseSerializedFieldType[] = [
    'lazy_table',
    'virtual_table',
    'view',
    'materialized_view',
]

/**
 * Columns the given data warehouse tables offer as a breakdown or a property, one join deep.
 * A joined column keeps the dotted path (`campaigns.name`), which the backend splits back into a
 * field chain. The join field itself is dropped, because it resolves to a table and not to a value.
 */
export function dataWarehouseColumnsWithJoins(
    tableNames: string[],
    tablesMap: Record<string, DatabaseSchemaTable>
): DatabaseSchemaField[] {
    const columns: DatabaseSchemaField[] = []

    for (const tableName of tableNames) {
        for (const field of Object.values(tablesMap[tableName]?.fields ?? {})) {
            if (!HIDDEN_FIELD_TYPES.includes(field.type)) {
                columns.push(field)
                continue
            }
            if (!field.table) {
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
