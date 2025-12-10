import { actions, afterMount, connect, kea, listeners, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { performQuery } from '~/queries/query'
import { DatabaseSchemaField, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'

export interface BIQueryColumn {
    table: string
    field: string
}

export interface BIQueryFilter {
    column: BIQueryColumn
    expression: string
}

export const biLogic = kea([
    connect({
        values: [databaseTableListLogic, ['dataWarehouseTables', 'posthogTables', 'systemTables', 'database']],
        actions: [databaseTableListLogic, ['loadDatabase', 'loadDatabaseSuccess']],
    }),
    actions({
        selectTable: (table: string) => ({ table }),
        addColumn: (column: BIQueryColumn) => ({ column }),
        removeColumn: (column: BIQueryColumn) => ({ column }),
        addFilter: (filter: BIQueryFilter) => ({ filter }),
        removeFilter: (column: BIQueryColumn) => ({ column }),
        setSort: (column: BIQueryColumn | null) => ({ column }),
        setLimit: (limit: number) => ({ limit }),
        setSearchTerm: (term: string) => ({ term }),
        refreshQuery: true,
    }),
    reducers({
        selectedTable: [
            null as string | null,
            {
                selectTable: (state, { table }) => (state === table ? null : table),
            },
        ],
        selectedColumns: [
            [] as BIQueryColumn[],
            {
                addColumn: (state, { column }) => {
                    if (state.find((col) => col.table === column.table && col.field === column.field)) {
                        return state
                    }
                    return [...state, column]
                },
                removeColumn: (state, { column }) =>
                    state.filter((col) => !(col.table === column.table && col.field === column.field)),
                selectTable: (state, { table }) => state.filter((col) => col.table === table),
            },
        ],
        filters: [
            [] as BIQueryFilter[],
            {
                addFilter: (state, { filter }) => {
                    const withoutExisting = state.filter(
                        (item) =>
                            !(item.column.table === filter.column.table && item.column.field === filter.column.field)
                    )
                    return [...withoutExisting, filter]
                },
                removeFilter: (state, { column }) =>
                    state.filter((item) => !(item.column.table === column.table && item.column.field === column.field)),
                removeColumn: (state, { column }) =>
                    state.filter((item) => !(item.column.table === column.table && item.column.field === column.field)),
                selectTable: () => [],
            },
        ],
        sort: [null as BIQueryColumn | null, { setSort: (_, { column }) => column, selectTable: () => null }],
        limit: [50 as number, { setLimit: (_, { limit }) => limit }],
        searchTerm: ['', { setSearchTerm: (_, { term }) => term }],
    }),
    selectors({
        allTables: [
            (s) => [s.dataWarehouseTables, s.posthogTables, s.systemTables],
            (dataWarehouseTables, posthogTables, systemTables) =>
                [...dataWarehouseTables, ...posthogTables, ...systemTables].sort((a, b) =>
                    a.name.localeCompare(b.name)
                ),
        ],
        selectedTableObject: [
            (s) => [s.allTables, s.selectedTable],
            (tables, selectedTable) => tables.find((table) => table.name === selectedTable) || null,
        ],
        filteredTables: [
            (s) => [s.allTables, s.searchTerm],
            (tables, searchTerm) =>
                tables.filter(
                    (table) =>
                        table.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
                        Object.values(table.fields || {}).some((field) =>
                            field.name.toLowerCase().includes(searchTerm.toLowerCase())
                        )
                ),
        ],
        selectedFields: [
            (s) => [s.selectedColumns, s.selectedTableObject],
            (columns, table) =>
                columns
                    .map((column) => ({
                        column,
                        field: table?.fields?.[column.field] as DatabaseSchemaField | undefined,
                    }))
                    .filter((item) => !!item.field) as { column: BIQueryColumn; field: DatabaseSchemaField }[],
        ],
        queryString: [
            (s) => [s.selectedTableObject, s.selectedFields, s.filters, s.sort, s.limit],
            (table, selectedFields, filters, sort, limit) => {
                if (!table || selectedFields.length === 0) {
                    return ''
                }

                const selectParts = selectedFields.map(
                    ({ field, column }) => `${field.hogql_value} AS "${column.field}"`
                )
                const whereParts = filters
                    .map(({ column, expression }) => {
                        const field = table.fields[column.field]
                        return `${field.hogql_value} ${expression}`
                    })
                    .filter(Boolean)

                const orderBy = sort
                    ? `\nORDER BY ${table.fields[sort.field]?.hogql_value || sort.field} ${sort ? 'ASC' : ''}`
                    : ''
                const where = whereParts.length > 0 ? `\nWHERE ${whereParts.join(' AND ')}` : ''
                const limitSql = limit ? `\nLIMIT ${limit}` : ''

                return `SELECT ${selectParts.join(', ')}\nFROM ${table.name} ${where}${orderBy}${limitSql}`
            },
        ],
        _queryString: [
            (s) => [s.queryString],
            (queryString) => {
                if (!queryString) {
                    return ''
                }
                if (queryString.includes('postgres.') || queryString.includes('posthog_')) {
                    return '--pg\n' + queryString
                }
                return queryString
            },
        ],
    }),
    loaders(({ values }) => ({
        queryResponse: [
            null as HogQLQueryResponse<any[]> | null,
            {
                loadQueryResponse: async () => {
                    if (!values._queryString) {
                        return null
                    }

                    return await performQuery(
                        setLatestVersionsOnQuery({
                            kind: NodeKind.HogQLQuery,
                            query: values._queryString,
                        })
                    )
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        addColumn: () => actions.loadQueryResponse(),
        removeColumn: () => actions.loadQueryResponse(),
        addFilter: () => actions.loadQueryResponse(),
        removeFilter: () => actions.loadQueryResponse(),
        selectTable: () => actions.loadQueryResponse(),
        setSort: () => actions.loadQueryResponse(),
        setLimit: () => actions.loadQueryResponse(),
        refreshQuery: () => actions.loadQueryResponse(),
        loadDatabaseSuccess: ({ database }) => {
            if (database?.tables && Object.keys(database.tables).length > 0) {
                const firstTable = Object.values(database.tables)[0]
                actions.selectTable(firstTable.name)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDatabase()
    }),
])

export function columnKey(column: BIQueryColumn): string {
    return `${column.table}.${column.field}`
}
