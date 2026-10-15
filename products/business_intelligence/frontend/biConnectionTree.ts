import { TableFieldsStatus } from 'scenes/data-management/database/databaseTableListLogic'

import { BIDataSource } from '~/queries/schema/schema-business-intelligence'
import { DatabaseSchemaField, DatabaseSchemaTable } from '~/queries/schema/schema-general'

import { BIDataPaneFields, getBIDataPaneFields } from 'products/business_intelligence/frontend/biEditorTypes'
import { resolveFieldTraverserTarget } from 'products/data_warehouse/frontend/shared/fieldTraversal'

import { matchesBIFieldSearch } from './biPropertyFields'

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

function getHydrationKey(table: DatabaseSchemaTable): string {
    return table.type === 'posthog' ? table.id : table.name
}

function getConnectionState(
    field: DatabaseSchemaField,
    table: DatabaseSchemaTable | null,
    status: TableFieldsStatus[string] | undefined,
    complete: boolean
): BIConnection['state'] {
    if (field.type === 'virtual_table') {
        return 'ready'
    }
    if (status === 'error' || status === 'missing') {
        return status
    }
    if (table && !complete && !Object.keys(table.fields).length && status !== 'loaded') {
        return 'loading'
    }
    return !table && !field.fields?.length ? 'missing' : 'ready'
}

function getConnectionFields(field: DatabaseSchemaField, table: DatabaseSchemaTable | null): DatabaseSchemaField[] {
    // A virtual table's printed table is not the owner of its child field definitions.
    const fieldsTable = field.type === 'virtual_table' ? null : table
    return field.fields?.length
        ? field.fields
              .filter((name) => name !== 'team_id')
              .map(
                  (name): DatabaseSchemaField =>
                      fieldsTable?.fields[name] ?? {
                          name,
                          hogql_value: name,
                          type: 'unknown',
                          schema_valid: true,
                      }
              )
        : Object.values(fieldsTable?.fields ?? {}).filter(
              (child) => child.name !== 'team_id' || child.type !== 'unknown'
          )
}

export function buildBIConnections(
    source: BIDataSource,
    tables: Record<string, DatabaseSchemaTable>,
    expandedIds: string[],
    tableFieldsStatus: TableFieldsStatus,
    databaseFieldsComplete: boolean
): BIConnection[] {
    const expanded = new Set(expandedIds)
    const getTable = (name?: string): DatabaseSchemaTable | null =>
        name ? (tables[name] ?? tables[name.replaceAll('`', '')] ?? null) : null
    const visit = (tableName: string, fields: DatabaseSchemaField[], path: string[]): BIConnection[] => {
        const tableLookup = {
            ...tables,
            [tableName]: { name: tableName, fields: Object.fromEntries(fields.map((field) => [field.name, field])) },
        }
        return fields
            .flatMap((originalField): BIConnection[] => {
                let pendingTableName: string | undefined
                const field =
                    originalField.type === 'field_traverser'
                        ? resolveFieldTraverserTarget(tableName, originalField, tableLookup, new Set(), (name) => {
                              pendingTableName = name
                          })
                        : originalField
                const pendingTable = pendingTableName ? getTable(pendingTableName) : null
                const pendingState = pendingTable
                    ? getConnectionState(
                          originalField,
                          pendingTable,
                          tableFieldsStatus[getHydrationKey(pendingTable)],
                          databaseFieldsComplete
                      )
                    : null
                if (
                    (!field || !['lazy_table', 'virtual_table', 'view', 'materialized_view'].includes(field.type)) &&
                    (!pendingState || pendingState === 'ready')
                ) {
                    return []
                }
                const childPath = [...path, originalField.name]
                const id = JSON.stringify(childPath)
                const table = pendingTable ?? (field?.type === 'virtual_table' ? null : getTable(field?.table))
                const status = table ? tableFieldsStatus[getHydrationKey(table)] : undefined
                const state = pendingState ?? getConnectionState(field!, table, status, databaseFieldsComplete)
                const connection: BIConnection = {
                    id,
                    name: originalField.name,
                    path: childPath,
                    tableName: table ? getHydrationKey(table) : undefined,
                    expanded: expanded.has(id),
                    state,
                    fields: { dimensions: [], measures: [] },
                    connections: [],
                }
                if (!connection.expanded || state !== 'ready' || !field) {
                    return [connection]
                }
                const childFields = getConnectionFields(field, table)
                const nestedTableName = table?.name ?? field.table ?? tableName
                const childLookup = {
                    ...tables,
                    [nestedTableName]: {
                        name: nestedTableName,
                        fields: Object.fromEntries(childFields.map((child) => [child.name, child])),
                    },
                }
                const scalarFields = childFields.map((child) => {
                    const resolved =
                        child.type === 'field_traverser'
                            ? resolveFieldTraverserTarget(nestedTableName, child, childLookup)
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
    }
    return visit(source.table, Object.values(getTable(source.table)?.fields ?? {}), [])
}

export function getPendingBIConnectionTables(connections: BIConnection[]): string[] {
    return [
        ...new Set(
            connections.flatMap((connection) =>
                connection.expanded
                    ? [
                          ...(connection.state === 'loading' && connection.tableName ? [connection.tableName] : []),
                          ...getPendingBIConnectionTables(connection.connections),
                      ]
                    : []
            )
        ),
    ]
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
            dimensions: connection.fields.dimensions.filter((field) => matchesBIFieldSearch(field, term)),
            measures: connection.fields.measures.filter((field) => matchesBIFieldSearch(field, term)),
        }
        const children = filterBIConnections(connection.connections, term)
        return !connection.expanded ||
            fields.dimensions.length ||
            fields.measures.length ||
            children.length ||
            connection.state === 'loading' ||
            connection.state === 'error'
            ? [{ ...connection, fields, connections: children }]
            : []
    })
}
