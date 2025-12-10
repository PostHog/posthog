import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { urls } from 'scenes/urls'

import { performQuery } from '~/queries/query'
import { DatabaseSchemaField, DatabaseSchemaTable, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'

import type { biLogicType } from './biLogicType'

export type BIAggregation = 'count' | 'min' | 'max' | 'sum'
export type BITimeAggregation = 'hour' | 'day' | 'week' | 'month'
export type BISortDirection = 'asc' | 'desc'

export interface BISort {
    column: BIQueryColumn
    direction: BISortDirection
}

export interface BIQueryColumn {
    table: string
    field: string
    aggregation?: BIAggregation
    timeInterval?: BITimeAggregation
}

export interface BIQueryFilter {
    column: BIQueryColumn
    expression: string
}

export const biLogic = kea<biLogicType>([
    path(['scenes', 'bi', 'biLogic']),
    tabAwareScene(),
    connect({
        values: [
            databaseTableListLogic,
            ['dataWarehouseTables', 'posthogTables', 'systemTables', 'database', 'databaseLoading'],
        ],
        actions: [databaseTableListLogic, ['loadDatabase', 'loadDatabaseSuccess']],
    }),
    actions({
        selectTable: (table: string | null) => ({ table }),
        addColumn: (column: BIQueryColumn) => ({ column }),
        setColumnAggregation: (column: BIQueryColumn, aggregation?: BIAggregation | null) => ({
            column,
            aggregation,
        }),
        setColumnTimeInterval: (column: BIQueryColumn, timeInterval?: BITimeAggregation | null) => ({
            column,
            timeInterval,
        }),
        setColumns: (columns: BIQueryColumn[]) => ({ columns }),
        removeColumn: (column: BIQueryColumn) => ({ column }),
        addFilter: (filter: BIQueryFilter) => ({ filter }),
        setFilters: (filters: BIQueryFilter[]) => ({ filters }),
        updateFilter: (index: number, expression: string) => ({ index, expression }),
        removeFilter: (index: number) => ({ index }),
        setSort: (column: BIQueryColumn | null, direction?: BISortDirection | null) => ({ column, direction }),
        setLimit: (limit: number) => ({ limit }),
        setTableSearchTerm: (term: string) => ({ term }),
        setColumnSearchTerm: (term: string) => ({ term }),
        refreshQuery: true,
        resetSelection: true,
    }),
    reducers({
        selectedTable: [
            null as string | null,
            {
                selectTable: (_, { table }) => table,
                resetSelection: () => null,
            },
        ],
        selectedColumns: [
            [] as BIQueryColumn[],
            {
                addColumn: (state, { column }) => {
                    if (state.find((col) => columnsEqual(col, column))) {
                        return state
                    }
                    return [...state, column]
                },
                setColumnAggregation: (state, { column, aggregation }) =>
                    state.map((col) =>
                        columnsEqual(col, column) ? { ...col, aggregation: aggregation || undefined } : col
                    ),
                setColumnTimeInterval: (state, { column, timeInterval }) =>
                    state.map((col) =>
                        columnsEqual(col, column) ? { ...col, timeInterval: timeInterval || undefined } : col
                    ),
                removeColumn: (state, { column }) => state.filter((col) => !columnsEqual(col, column)),
                selectTable: (state, { table }) => state.filter((col) => col.table === table),
                setColumns: (_, { columns }) => uniqueColumns(columns),
                resetSelection: () => [],
            },
        ],
        filters: [
            [] as BIQueryFilter[],
            {
                addFilter: (state, { filter }) => {
                    return [...state, filter]
                },
                setFilters: (_, { filters }) => filters,
                updateFilter: (state, { index, expression }) =>
                    state.map((filter, filterIndex) => (index === filterIndex ? { ...filter, expression } : filter)),
                removeFilter: (state, { index }) => state.filter((_, filterIndex) => filterIndex !== index),
                removeColumn: (state, { column }) => state.filter((item) => !columnsEqual(item.column, column)),
                selectTable: () => [],
                resetSelection: () => [],
            },
        ],
        sort: [
            null as BISort | null,
            {
                setSort: (state, { column, direction }) => {
                    if (!column || !direction) {
                        return null
                    }

                    if (state && columnsEqual(state.column, column) && state.direction === direction) {
                        return null
                    }

                    return { column, direction }
                },
                selectTable: () => null,
                resetSelection: () => null,
            },
        ],
        limit: [50 as number, { setLimit: (_, { limit }) => limit, resetSelection: () => 50 }],
        tableSearchTerm: [
            '',
            {
                setTableSearchTerm: (_, { term }) => term,
            },
        ],
        columnSearchTerm: [
            '',
            {
                setColumnSearchTerm: (_, { term }) => term,
                resetSelection: () => '',
                selectTable: () => '',
            },
        ],
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
            (s) => [s.allTables, s.tableSearchTerm],
            (tables, tableSearchTerm) =>
                tables.filter(
                    (table) =>
                        table.name.toLowerCase().includes(tableSearchTerm.toLowerCase()) ||
                        Object.values(table.fields || {}).some((field) =>
                            field.name.toLowerCase().includes(tableSearchTerm.toLowerCase())
                        )
                ),
        ],
        selectedFields: [
            (s) => [s.selectedColumns, s.selectedTableObject],
            (columns, table) => {
                if (!table) {
                    return []
                }
                return columns
                    .map((column) => {
                        const field = table?.fields?.[column.field] as DatabaseSchemaField | undefined
                        if (!field) {
                            return null
                        }

                        return {
                            column,
                            field,
                            alias: columnAlias(column),
                            expression: columnExpression(column, field, table),
                        }
                    })
                    .filter(Boolean) as {
                    column: BIQueryColumn
                    field: DatabaseSchemaField
                    alias: string
                    expression: string
                }[]
            },
        ],
        filteredFields: [
            (s) => [s.selectedTableObject, s.columnSearchTerm],
            (table, columnSearchTerm) => {
                if (!table) {
                    return []
                }

                const fields = Object.values(table.fields || {})
                if (!columnSearchTerm) {
                    return fields
                }
                return fields.filter((field) => field.name.toLowerCase().includes(columnSearchTerm.toLowerCase()))
            },
        ],
        searchTerm: [
            (s) => [s.selectedTableObject, s.tableSearchTerm, s.columnSearchTerm],
            (selectedTableObject, tableSearchTerm, columnSearchTerm) =>
                selectedTableObject ? columnSearchTerm : tableSearchTerm,
        ],
        queryString: [
            (s) => [s.selectedTableObject, s.selectedFields, s.filters, s.sort, s.limit],
            (table, selectedFields, filters, sort, limit) => {
                if (!table || selectedFields.length === 0) {
                    return ''
                }

                const selectParts = selectedFields.map(({ expression, alias }) => `${expression} AS "${alias}"`)

                const whereParts: string[] = []
                const havingParts: string[] = []

                filters.forEach(({ column, expression }) => {
                    const field = table.fields[column.field]
                    if (!field) {
                        return
                    }

                    const target = columnExpression(column, field, table)
                    if (column.aggregation) {
                        havingParts.push(`${target} ${expression}`)
                    } else {
                        whereParts.push(`${target} ${expression}`)
                    }
                })

                const groupByColumns = selectedFields
                    .filter(({ column }) => !column.aggregation)
                    .map(({ expression }) => expression)
                const hasAggregations = selectedFields.some(({ column }) => column.aggregation)

                const orderBy = sort ? `\nORDER BY "${columnAlias(sort.column)}" ${sort.direction.toUpperCase()}` : ''
                const where = whereParts.length > 0 ? `\nWHERE ${whereParts.join(' AND ')}` : ''
                const groupBy =
                    hasAggregations && groupByColumns.length > 0 ? `\nGROUP BY ${groupByColumns.join(', ')}` : ''
                const having = havingParts.length > 0 ? `\nHAVING ${havingParts.join(' AND ')}` : ''
                const limitSql = limit ? `\nLIMIT ${limit}` : ''

                return `SELECT ${selectParts.join(', ')}\nFROM ${table.name} ${where}${groupBy}${having}${orderBy}${limitSql}`
            },
        ],
        _queryString: [
            (s) => [s.queryString, s.selectedTableObject],
            (queryString, table) => {
                if (!queryString) {
                    return ''
                }
                if (table && getTableDialect(table) === 'postgres') {
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
            {
                resetSelection: () => null,
                selectTable: () => null,
            },
        ],
    })),
    tabAwareActionToUrl(({ values }) => ({
        addColumn: () => [urls.bi(), buildBiSearchParams(values), router.values.hashParams, { replace: true }],
        setColumnAggregation: () => [
            urls.bi(),
            buildBiSearchParams(values),
            router.values.hashParams,
            { replace: true },
        ],
        setColumnTimeInterval: () => [
            urls.bi(),
            buildBiSearchParams(values),
            router.values.hashParams,
            { replace: true },
        ],
        removeColumn: () => [urls.bi(), buildBiSearchParams(values), router.values.hashParams, { replace: true }],
        addFilter: () => [urls.bi(), buildBiSearchParams(values), router.values.hashParams, { replace: true }],
        updateFilter: () => [urls.bi(), buildBiSearchParams(values), router.values.hashParams, { replace: true }],
        removeFilter: () => [urls.bi(), buildBiSearchParams(values), router.values.hashParams, { replace: true }],
        selectTable: () => [urls.bi(), buildBiSearchParams(values), router.values.hashParams, { replace: true }],
        setSort: () => [urls.bi(), buildBiSearchParams(values), router.values.hashParams, { replace: true }],
        setLimit: () => [urls.bi(), buildBiSearchParams(values), router.values.hashParams, { replace: true }],
        setTableSearchTerm: () => [urls.bi(), buildBiSearchParams(values), router.values.hashParams, { replace: true }],
        resetSelection: () => [urls.bi(), buildBiSearchParams(values), router.values.hashParams, { replace: true }],
        setColumns: () => [urls.bi(), buildBiSearchParams(values), router.values.hashParams, { replace: true }],
        setFilters: () => [urls.bi(), buildBiSearchParams(values), router.values.hashParams, { replace: true }],
    })),
    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.bi()]: (_params, searchParams) => {
            const table = typeof searchParams.table === 'string' ? searchParams.table : null
            const limit = Number.isFinite(Number(searchParams.limit)) ? Number(searchParams.limit) : 50
            const searchTerm = typeof searchParams.q === 'string' ? searchParams.q : ''

            if (!table) {
                if (values.selectedTable) {
                    actions.resetSelection()
                }
                if (limit !== values.limit) {
                    actions.setLimit(limit)
                }
                if (searchTerm !== values.tableSearchTerm) {
                    actions.setTableSearchTerm(searchTerm)
                }
                return
            }

            const columns = parseColumnsParam(searchParams.columns, table)
            const filters = parseFiltersParam(searchParams.filters, table)
            const sort = parseSortParam(searchParams.sort, table)

            if (table !== values.selectedTable) {
                actions.selectTable(table)
            }
            if (!columnsListsEqual(columns, values.selectedColumns)) {
                actions.setColumns(columns)
            }
            if (searchTerm !== values.tableSearchTerm) {
                actions.setTableSearchTerm(searchTerm)
            }
            if (!filtersEqual(filters, values.filters)) {
                actions.setFilters(filters)
            }
            if (!sortsEqual(sort, values.sort)) {
                actions.setSort(sort?.column || null, sort?.direction)
            }
            if (limit !== values.limit) {
                actions.setLimit(limit)
            }
        },
    })),
    listeners(({ actions, values }) => ({
        addColumn: () => actions.loadQueryResponse(),
        setColumnAggregation: () => actions.loadQueryResponse(),
        setColumnTimeInterval: () => actions.loadQueryResponse(),
        setColumns: () => actions.loadQueryResponse(),
        removeColumn: () => actions.loadQueryResponse(),
        addFilter: () => actions.loadQueryResponse(),
        setFilters: () => actions.loadQueryResponse(),
        updateFilter: () => actions.loadQueryResponse(),
        removeFilter: () => actions.loadQueryResponse(),
        selectTable: ({ table }) => table && actions.loadQueryResponse(),
        setSort: () => actions.loadQueryResponse(),
        setLimit: () => actions.loadQueryResponse(),
        refreshQuery: () => actions.loadQueryResponse(),
        loadDatabaseSuccess: () => {
            if (values.queryString && values.selectedFields.length > 0 && !values.queryResponse) {
                actions.loadQueryResponse()
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDatabase()
    }),
])

export function columnKey(column: BIQueryColumn): string {
    return `${column.table}.${column.field}.${column.aggregation || 'raw'}.${column.timeInterval || 'none'}`
}

export function columnAlias(column: BIQueryColumn): string {
    let alias = column.field

    if (column.timeInterval) {
        alias = `${column.timeInterval}_of_${alias}`
    }

    if (column.aggregation) {
        alias = ['min', 'max'].includes(column.aggregation)
            ? `${column.aggregation}_${alias}`
            : `${column.aggregation}_of_${alias}`
    }

    return alias
}

function columnExpression(column: BIQueryColumn, field: DatabaseSchemaField, table: DatabaseSchemaTable): string {
    const timeExpression = column.timeInterval
        ? wrapTimeAggregation(field.hogql_value, column.timeInterval, table)
        : field.hogql_value

    if (column.aggregation) {
        return `${column.aggregation}(${timeExpression})`
    }
    return timeExpression
}

function columnsEqual(a: BIQueryColumn | null | undefined, b: BIQueryColumn | null | undefined): boolean {
    if (!a && !b) {
        return true
    }
    if (!a || !b) {
        return false
    }
    return columnKey(a) === columnKey(b)
}

function sortsEqual(a: BISort | null, b: BISort | null): boolean {
    if (!a && !b) {
        return true
    }
    if (!a || !b) {
        return false
    }

    return columnsEqual(a.column, b.column) && a.direction === b.direction
}

function columnsListsEqual(a: BIQueryColumn[], b: BIQueryColumn[]): boolean {
    if (a.length !== b.length) {
        return false
    }
    return a.every((item, index) => columnsEqual(item, b[index]))
}

function filtersEqual(a: BIQueryFilter[], b: BIQueryFilter[]): boolean {
    if (a.length !== b.length) {
        return false
    }
    return a.every(
        (filter, index) => columnsEqual(filter.column, b[index].column) && filter.expression === b[index].expression
    )
}

function uniqueColumns(columns: BIQueryColumn[]): BIQueryColumn[] {
    const seen = new Set<string>()
    return columns.filter((column) => {
        const key = columnKey(column)
        if (seen.has(key)) {
            return false
        }
        seen.add(key)
        return true
    })
}

function buildBiSearchParams(values: any): Record<string, any> {
    const params: Record<string, any> = {}
    if (values.selectedTable) {
        params.table = values.selectedTable
    }
    const serializedColumns = serializeColumns(values.selectedColumns)
    if (serializedColumns) {
        params.columns = serializedColumns
    }
    const serializedFilters = serializeFilters(values.filters)
    if (serializedFilters) {
        params.filters = serializedFilters
    }
    if (values.sort) {
        params.sort = serializeSort(values.sort)
    }
    if (values.limit && values.limit !== 50) {
        params.limit = values.limit
    }
    if (values.tableSearchTerm) {
        params.q = values.tableSearchTerm
    }
    return params
}

function serializeColumns(columns: BIQueryColumn[]): string | undefined {
    if (!columns.length) {
        return undefined
    }
    return columns
        .map((column) => `${column.aggregation || 'raw'}:${column.timeInterval || 'raw'}:${column.field}`)
        .join(',')
}

function serializeFilters(filters: BIQueryFilter[]): string | undefined {
    if (!filters.length) {
        return undefined
    }
    return JSON.stringify(
        filters.map(({ column, expression }) => ({
            field: column.field,
            aggregation: column.aggregation,
            timeInterval: column.timeInterval,
            expression,
        }))
    )
}

function serializeSort(sort: BISort): string {
    return `${sort.direction}:${sort.column.aggregation || 'raw'}:${sort.column.timeInterval || 'raw'}:${sort.column.field}`
}

function parseColumnsParam(param: any, table: string | null): BIQueryColumn[] {
    if (!table || !param) {
        return []
    }
    return String(param)
        .split(',')
        .filter(Boolean)
        .map((item) => parseColumnItem(item, table))
        .filter(Boolean) as BIQueryColumn[]
}

function parseFiltersParam(param: any, table: string | null): BIQueryFilter[] {
    if (!table || !param || typeof param !== 'string') {
        return []
    }
    try {
        const parsed = JSON.parse(param)
        if (!Array.isArray(parsed)) {
            return []
        }
        return parsed
            .map((item) => {
                if (typeof item?.field !== 'string' || typeof item?.expression !== 'string') {
                    return null
                }
                const aggregation =
                    typeof item.aggregation === 'string' && ['count', 'min', 'max', 'sum'].includes(item.aggregation)
                        ? (item.aggregation as BIAggregation)
                        : undefined
                const timeInterval =
                    typeof item.timeInterval === 'string' &&
                    ['hour', 'day', 'week', 'month'].includes(item.timeInterval)
                        ? (item.timeInterval as BITimeAggregation)
                        : undefined
                return {
                    column: { table, field: item.field, aggregation, timeInterval },
                    expression: item.expression,
                }
            })
            .filter(Boolean) as BIQueryFilter[]
    } catch {
        return []
    }
}

function parseSortParam(param: any, table: string | null): BISort | null {
    if (!table || !param) {
        return null
    }
    const [maybeDirection, ...rest] = String(param).split(':')
    const direction = maybeDirection === 'desc' ? 'desc' : 'asc'
    const columnFromNewFormat = parseColumnItem(rest.join(':'), table)

    if (columnFromNewFormat) {
        return { column: columnFromNewFormat, direction }
    }

    const legacyColumn = parseColumnItem(String(param), table)

    return legacyColumn ? { column: legacyColumn, direction: 'asc' } : null
}

function parseColumnItem(item: string, table: string): BIQueryColumn | null {
    const parts = item.split(':')

    if (parts.length === 1) {
        const field = parts[0]
        return field ? { table, field } : null
    }

    if (parts.length === 2) {
        const [maybeAggregation, field] = parts
        const aggregation = maybeAggregation === 'raw' ? undefined : maybeAggregation
        if (!field) {
            return null
        }
        if (aggregation && !['count', 'min', 'max', 'sum'].includes(aggregation)) {
            return null
        }
        return { table, field, aggregation: aggregation as BIAggregation | undefined }
    }

    const [maybeAggregation, maybeTimeInterval, ...rest] = parts
    const field = rest.join(':')
    const aggregation = maybeAggregation === 'raw' ? undefined : maybeAggregation
    const timeInterval = maybeTimeInterval === 'raw' ? undefined : maybeTimeInterval

    if (!field) {
        return null
    }

    if (aggregation && !['count', 'min', 'max', 'sum'].includes(aggregation)) {
        return null
    }
    if (timeInterval && !['hour', 'day', 'week', 'month'].includes(timeInterval)) {
        return null
    }

    return {
        table,
        field,
        aggregation: aggregation as BIAggregation | undefined,
        timeInterval: (timeInterval as BITimeAggregation | undefined) || undefined,
    }
}

function wrapTimeAggregation(value: string, interval: BITimeAggregation, table: DatabaseSchemaTable): string {
    if (getTableDialect(table) === 'postgres') {
        return `date_trunc('${interval}', ${value})`
    }

    switch (interval) {
        case 'hour':
            return `toStartOfHour(${value})`
        case 'week':
            return `toStartOfWeek(${value})`
        case 'month':
            return `toStartOfMonth(${value})`
        case 'day':
        default:
            return `toStartOfDay(${value})`
    }
}

function getTableDialect(table: DatabaseSchemaTable): 'postgres' | 'clickhouse' {
    return (table as any)?.source?.source_type === 'Postgres' ? 'postgres' : 'clickhouse'
}
