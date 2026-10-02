import { TableFieldsStatus } from 'scenes/data-management/database/databaseTableListLogic'
import { BIDataPaneFields, BIDataSource, getBIDataPaneFields } from 'scenes/data-warehouse/editor/bi/biEditorTypes'
import { resolveFieldTraverserTarget } from 'scenes/data-warehouse/editor/sidebar/queryDatabaseLogic'

import { DatabaseSchemaField, DatabaseSchemaTable } from '~/queries/schema/schema-general'

export interface BIConnection {
    id: string
    name: string
    path: string[]
    tableName?: string
    expanded: boolean
    state: 'ready' | 'loading' | 'error' | 'missing'
    fields: BIDataPaneFields
    connections: BIConnection[]
}

function getConnectionState(
    field: DatabaseSchemaField,
    table: DatabaseSchemaTable | undefined,
    status: TableFieldsStatus[string] | undefined,
    complete: boolean
): BIConnection['state'] {
    if (status === 'error' || status === 'missing') {
        return status
    }
    if (table && !complete && !Object.keys(table.fields).length && status !== 'loaded') {
        return 'loading'
    }
    return !table && !field.fields?.length ? 'missing' : 'ready'
}

function getConnectionFields(
    field: DatabaseSchemaField,
    table: DatabaseSchemaTable | undefined
): DatabaseSchemaField[] {
    return field.fields?.length
        ? field.fields
              .filter((name) => name !== 'team_id')
              .map(
                  (name): DatabaseSchemaField =>
                      table?.fields[name] ?? {
                          name,
                          hogql_value: name,
                          type: 'unknown',
                          schema_valid: true,
                      }
              )
        : Object.values(table?.fields ?? {}).filter((child) => child.name !== 'team_id' || child.type !== 'unknown')
}

export function buildBIConnections(
    source: BIDataSource,
    tables: Record<string, DatabaseSchemaTable>,
    expandedIds: string[],
    tableFieldsStatus: TableFieldsStatus,
    databaseFieldsComplete: boolean
): BIConnection[] {
    const expanded = new Set(expandedIds)
    const getTable = (name?: string): DatabaseSchemaTable | undefined =>
        name ? (tables[name] ?? tables[name.replaceAll('`', '')]) : undefined
    const visit = (tableName: string, fields: DatabaseSchemaField[], path: string[]): BIConnection[] =>
        fields
            .flatMap((originalField): BIConnection[] => {
                const field =
                    originalField.type === 'field_traverser'
                        ? resolveFieldTraverserTarget(tableName, originalField, tables)
                        : originalField
                if (!field || !['lazy_table', 'virtual_table', 'view', 'materialized_view'].includes(field.type)) {
                    return []
                }
                const childPath = [...path, originalField.name]
                const id = JSON.stringify(childPath)
                const table = getTable(field.table)
                const status = table ? tableFieldsStatus[table.name] : undefined
                const state = getConnectionState(field, table, status, databaseFieldsComplete)
                const connection: BIConnection = {
                    id,
                    name: originalField.name,
                    path: childPath,
                    tableName: table?.name,
                    expanded: expanded.has(id),
                    state,
                    fields: { dimensions: [], measures: [] },
                    connections: [],
                }
                if (!connection.expanded || state !== 'ready') {
                    return [connection]
                }
                const childFields = getConnectionFields(field, table)
                const nestedTableName = table?.name ?? field.table ?? tableName
                const scalarFields = childFields.map((child) => {
                    const resolved =
                        child.type === 'field_traverser'
                            ? resolveFieldTraverserTarget(nestedTableName, child, tables)
                            : child
                    return resolved ? { ...resolved, name: child.name } : child
                })
                return [
                    {
                        ...connection,
                        fields: getBIDataPaneFields(
                            { fields: Object.fromEntries(scalarFields.map((child) => [child.name, child])) },
                            source,
                            childPath
                        ),
                        connections: visit(nestedTableName, childFields, childPath),
                    },
                ]
            })
            .sort((left, right) => left.name.localeCompare(right.name))
    return visit(source.table, Object.values(getTable(source.table)?.fields ?? {}), [])
}

export function filterBIConnections(connections: BIConnection[], search: string): BIConnection[] {
    const term = search.trim().toLowerCase()
    if (!term) {
        return connections
    }
    return connections.flatMap((connection) => {
        if (connection.path.join('.').toLowerCase().includes(term)) {
            return [connection]
        }
        const fields = {
            dimensions: connection.fields.dimensions.filter((field) => field.name.toLowerCase().includes(term)),
            measures: connection.fields.measures.filter((field) => field.name.toLowerCase().includes(term)),
        }
        const children = filterBIConnections(connection.connections, term)
        return !connection.expanded || fields.dimensions.length || fields.measures.length || children.length
            ? [{ ...connection, fields, connections: children }]
            : []
    })
}
