import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { externalDataSourcesLogic } from 'scenes/data-warehouse/externalDataSourcesLogic'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { performQuery } from '~/queries/query'
import {
    DatabaseSchemaField,
    DatabaseSchemaForeignKey,
    DatabaseSchemaQueryResponse,
    DatabaseSchemaTable,
    DatabaseSerializedFieldType,
    HogQLQueryResponse,
    NodeKind,
} from '~/queries/schema/schema-general'
import { setLatestVersionsOnQuery } from '~/queries/utils'
import { Breadcrumb } from '~/types'

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

export interface FieldTreeNode {
    field: DatabaseSchemaField
    path: string
    children: FieldTreeNode[]
    hasChildren: boolean
}

export const biLogic = kea<biLogicType>([
    path(['scenes', 'bi', 'biLogic']),
    tabAwareScene(),
    connect({
        values: [
            databaseTableListLogic,
            ['dataWarehouseTables', 'posthogTables', 'systemTables', 'database', 'databaseLoading'],
            externalDataSourcesLogic,
            ['dataWarehouseSources'],
        ],
        actions: [
            databaseTableListLogic,
            ['loadDatabase', 'loadDatabaseSuccess'],
            externalDataSourcesLogic,
            ['loadSources', 'loadSourcesSuccess'],
        ],
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
        setExpandedFields: (paths: string[]) => ({ paths }),
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
        limit: [50 as number, { setLimit: (_, { limit }) => limit, resetSelection: () => 50, selectTable: () => 50 }],
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
        expandedFields: [
            [] as string[],
            {
                setExpandedFields: (_, { paths }) => paths,
                selectTable: () => [],
                resetSelection: () => [],
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
                tables.filter((table) => table.name.toLowerCase().includes(tableSearchTerm.toLowerCase())),
        ],
        selectedFields: [
            (s) => [s.selectedColumns, s.selectedTableObject, s.database],
            (columns, table, database) => {
                if (!table) {
                    return []
                }
                return columns
                    .map((column) => {
                        const resolution = resolveFieldAndExpression(column.field, table, database)
                        if (!resolution) {
                            return null
                        }

                        return {
                            column,
                            field: resolution.field,
                            alias: columnAlias(column),
                            expression: columnExpression(
                                column,
                                resolution.field,
                                table,
                                resolution.expression,
                                resolution.table
                            ),
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
        selectedFieldTrees: [
            (s) => [s.selectedTableObject, s.database, s.columnSearchTerm, s.expandedFields],
            (table, database, columnSearchTerm, expandedFields) =>
                buildFieldTrees(table, database, columnSearchTerm, expandedFields),
        ],
        searchTerm: [
            (s) => [s.selectedTableObject, s.tableSearchTerm, s.columnSearchTerm],
            (selectedTableObject, tableSearchTerm, columnSearchTerm) =>
                selectedTableObject ? columnSearchTerm : tableSearchTerm,
        ],
        breadcrumbs: [
            (s) => [s.selectedTableObject],
            (selectedTableObject): Breadcrumb[] => {
                const breadcrumbs: Breadcrumb[] = [
                    { key: Scene.BI, name: 'Data Explorer', path: urls.bi(), iconType: 'database' },
                ]

                if (selectedTableObject) {
                    breadcrumbs.push({
                        key: ['bi-table', selectedTableObject.name],
                        name: selectedTableObject.name,
                        path: urls.bi(),
                        iconType: 'database',
                    })
                }

                return breadcrumbs
            },
        ],
        queryString: [
            (s) => [s.selectedTableObject, s.selectedFields, s.filters, s.sort, s.limit, s.database],
            (table, selectedFields, filters, sort, limit, database) => {
                if (!table || selectedFields.length === 0) {
                    return ''
                }

                const selectParts = selectedFields.map(({ expression, alias }) => `${expression} AS "${alias}"`)

                const whereParts: string[] = []
                const havingParts: string[] = []

                filters.forEach(({ column, expression }) => {
                    const resolution = resolveFieldAndExpression(column.field, table, database)
                    if (!resolution) {
                        return
                    }

                    const target = columnExpression(
                        column,
                        resolution.field,
                        table,
                        resolution.expression,
                        resolution.table
                    )
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
                const limitSql = limit ? `\nLIMIT ${limit + 1}` : ''

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
                    const sourceId = getTableSourceId(table)
                    if (sourceId && isDirectQueryTable(table)) {
                        return `--pg:${sourceId}\n` + queryString
                    }
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
                        }),
                        undefined,
                        'force_blocking'
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
        selectTable: async ({ table }, breakpoint) => {
            if (!table) {
                return
            }

            await breakpoint(0)

            const selectedColumnsForTable = values.selectedColumns.filter((column) => column.table === table)

            if (selectedColumnsForTable.length === 0) {
                const tableObject = values.allTables.find((candidate) => candidate.name === table) || null
                const defaultColumn = defaultColumnForTable(tableObject)

                if (defaultColumn) {
                    actions.setColumns([defaultColumn])
                    return
                }
            }

            actions.loadQueryResponse()
        },
        setSort: () => actions.loadQueryResponse(),
        setLimit: () => actions.loadQueryResponse(),
        refreshQuery: () => actions.loadQueryResponse(),
        loadDatabaseSuccess: () => {
            if (values.queryString && values.selectedFields.length > 0 && !values.queryResponse) {
                actions.loadQueryResponse()
            }
        },
        loadSourcesSuccess: () => {
            actions.loadDatabase()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSources()
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

export function isJsonField(field?: DatabaseSchemaField): boolean {
    if (!field?.type || typeof field.type !== 'string') {
        return false
    }

    const type = field.type.toLowerCase()

    return type.includes('json') || type.includes('map') || type.includes('struct')
}

function columnExpression(
    column: BIQueryColumn,
    field: DatabaseSchemaField,
    table: DatabaseSchemaTable,
    expressionOverride?: string,
    fieldTable?: DatabaseSchemaTable
): string {
    const baseExpression = expressionOverride || field.hogql_value
    const timeExpression = column.timeInterval
        ? wrapTimeAggregation(baseExpression, column.timeInterval, fieldTable || table)
        : baseExpression

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

export function defaultColumnForTable(table: DatabaseSchemaTable | null): BIQueryColumn | null {
    if (!table) {
        return null
    }

    const fields = Object.values(table.fields || {})

    if (fields.length === 0) {
        return null
    }

    const defaultField = fields.find((field) => field.name.toLowerCase() === 'id') || fields[0]

    return { table: table.name, field: defaultField.name, aggregation: 'count' }
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

function resolveFieldAndExpression(
    fieldPath: string,
    table: DatabaseSchemaTable,
    database: DatabaseSchemaQueryResponse | null
): { field: DatabaseSchemaField; expression: string; table: DatabaseSchemaTable } | null {
    const parts = fieldPath.split('.')
    let currentTable: DatabaseSchemaTable | null = table
    let expression = ''
    let field: DatabaseSchemaField | undefined

    for (let index = 0; index < parts.length; index++) {
        const part = parts[index]
        const foreignKey = getForeignKeyForField(currentTable, part)
        const nextPart = parts[index + 1]

        if (foreignKey && currentTable?.fields?.[foreignKey.column]) {
            const foreignKeyField = currentTable.fields[foreignKey.column]
            const relationFieldName = foreignKeyFieldName(foreignKey.column)
            const foreignKeyExpression = expression
                ? `${expression}.${foreignKeyField.hogql_value}`
                : foreignKeyField.hogql_value
            const qualifiedTargetTableName = qualifyTableName(currentTable.name, foreignKey.target_table)
            const targetTable = getTableFromDatabase(database, qualifiedTargetTableName)
            const relationExpression = expression ? `${expression}.${relationFieldName}` : relationFieldName

            if (!nextPart || nextPart === foreignKey.target_column || !targetTable) {
                return {
                    field: foreignKeyField,
                    expression: targetTable ? relationExpression : foreignKeyExpression,
                    table: targetTable || currentTable,
                }
            }

            field = foreignKeyField
            expression = relationExpression
            currentTable = targetTable
            continue
        }

        const candidateField = currentTable?.fields?.[part]

        if (candidateField) {
            const { field: resolvedField, table: resolvedTable } = resolveFieldReference(
                candidateField,
                currentTable,
                database
            )

            field = resolvedField
            expression = expression ? `${expression}.${resolvedField.hogql_value}` : resolvedField.hogql_value

            if (index < parts.length - 1) {
                const targetTable = resolvedField.table ? getTableFromDatabase(database, resolvedField.table) : null
                const baseTableForChildren = targetTable || resolvedTable || currentTable

                if (resolvedField.fields?.length) {
                    const limitedTableFields = baseTableForChildren
                        ? {
                              ...baseTableForChildren,
                              fields: Object.fromEntries(
                                  resolvedField.fields.map((name) => {
                                      const childField = baseTableForChildren.fields?.[name]
                                      return [
                                          name,
                                          childField || {
                                              name,
                                              hogql_value: name,
                                              type: 'string' as DatabaseSerializedFieldType,
                                              schema_valid: true,
                                          },
                                      ]
                                  })
                              ),
                          }
                        : null

                    currentTable = limitedTableFields || baseTableForChildren
                } else if (targetTable) {
                    currentTable = targetTable
                } else if (resolvedTable && resolvedTable !== currentTable) {
                    currentTable = resolvedTable
                }
            }
        } else if (field && isJsonField(field)) {
            expression = expression ? `${expression}.${part}` : part
        } else {
            return null
        }

        if (index < parts.length - 1 && !(field && isJsonField(field)) && !currentTable) {
            return null
        }
    }

    if (!field || !currentTable) {
        return null
    }

    return { field, expression, table: currentTable }
}

function foreignKeyFieldName(column: string): string {
    return column.endsWith('_id') && column.length > 3 ? column.slice(0, -3) : column
}

function getForeignKeyForField(table: DatabaseSchemaTable | null, fieldName: string): DatabaseSchemaForeignKey | null {
    return (
        table?.schema_metadata?.foreign_keys?.find(
            (foreignKey) => foreignKeyFieldName(foreignKey.column) === fieldName
        ) || null
    )
}

function qualifyTableName(currentTableName: string, targetTableName: string): string {
    if (targetTableName.includes('.')) {
        return targetTableName
    }

    const [prefix] = currentTableName.split('.')
    return prefix ? `${prefix}.${targetTableName}` : targetTableName
}

function getForeignKeyColumnsToHide(table: DatabaseSchemaTable): Set<string> {
    const foreignKeys = table.schema_metadata?.foreign_keys || []

    return new Set(
        foreignKeys
            .map((foreignKey) => ({
                column: foreignKey.column,
                relationFieldName: foreignKeyFieldName(foreignKey.column),
            }))
            .filter(({ column, relationFieldName }) => column !== relationFieldName)
            .map(({ column }) => column)
    )
}

function buildFieldTreeNodes(
    table: DatabaseSchemaTable,
    database: DatabaseSchemaQueryResponse | null,
    parentPath: string,
    visitedTables: Set<string>,
    expandedPaths: Set<string>,
    forceExpandAll: boolean
): FieldTreeNode[] {
    const foreignKeyColumnsToHide = getForeignKeyColumnsToHide(table)
    const existingFieldNames = new Set(Object.keys(table.fields || {}))
    const primaryKeyFields = new Set(getPrimaryKeyFieldNames(table))

    const foreignKeyFields: DatabaseSchemaField[] = (table.schema_metadata?.foreign_keys || [])
        .map((foreignKey) => ({
            foreignKey,
            relationFieldName: foreignKeyFieldName(foreignKey.column),
            baseField: table.fields?.[foreignKey.column],
        }))
        .filter(({ relationFieldName, baseField }) => relationFieldName && baseField)
        .filter(({ relationFieldName }) => !existingFieldNames.has(relationFieldName))
        .map(({ foreignKey, relationFieldName, baseField }) => ({
            ...baseField!,
            name: relationFieldName,
            table: qualifyTableName(table.name, foreignKey.target_table),
            hogql_value: baseField?.hogql_value || foreignKey.column,
        }))

    const fields = [...getOrderedFields(table), ...foreignKeyFields]
        .filter((field) => !foreignKeyColumnsToHide.has(field.name))
        .sort((a, b) => {
            const aIsPrimaryKey = primaryKeyFields.has(a.name)
            const bIsPrimaryKey = primaryKeyFields.has(b.name)

            if (aIsPrimaryKey !== bIsPrimaryKey) {
                return aIsPrimaryKey ? -1 : 1
            }

            return a.name.localeCompare(b.name)
        })

    return fields.map((field) => {
        const path = parentPath ? `${parentPath}.${field.name}` : field.name
        const { field: resolvedField, table: resolvedTable } = resolveFieldReference(field, table, database)
        const targetTableName = resolvedField.table ? qualifyTableName(table.name, resolvedField.table) : null
        const targetTable = targetTableName ? getTableFromDatabase(database, targetTableName) : null
        const baseTableForChildren = targetTable || resolvedTable || table

        const hasExpandedDescendant = Array.from(expandedPaths).some((expandedPath) =>
            expandedPath.startsWith(`${path}.`)
        )
        const shouldExpandChildren = forceExpandAll || expandedPaths.has(path) || hasExpandedDescendant

        let limitedTableFields: DatabaseSchemaTable | null = null

        if (resolvedField.fields?.length) {
            const filteredFields = Object.fromEntries(
                resolvedField.fields.map((name) => {
                    const childField = baseTableForChildren.fields?.[name]
                    return [
                        name,
                        childField || {
                            name,
                            hogql_value: name,
                            type: 'string' as DatabaseSerializedFieldType,
                            schema_valid: true,
                        },
                    ]
                })
            )

            const tableNamePrefix = baseTableForChildren.name === table.name ? `${baseTableForChildren.name}.` : ''

            limitedTableFields = {
                ...baseTableForChildren,
                name: `${tableNamePrefix}${resolvedField.name}`,
                id: `${baseTableForChildren.id}.${resolvedField.name}`,
                fields: filteredFields,
            }
        } else if (baseTableForChildren.name !== table.name) {
            limitedTableFields = baseTableForChildren
        }

        const hasChildren = Boolean(
            limitedTableFields &&
                Object.keys(limitedTableFields.fields || {}).length > 0 &&
                !visitedTables.has(limitedTableFields.name)
        )

        const children =
            hasChildren && shouldExpandChildren
                ? buildFieldTreeNodes(
                      limitedTableFields!,
                      database,
                      path,
                      new Set<string>([...visitedTables, limitedTableFields!.name]),
                      expandedPaths,
                      forceExpandAll
                  )
                : []

        return { field, path, children, hasChildren }
    })
}

function getOrderedFields(table: DatabaseSchemaTable): DatabaseSchemaField[] {
    const fieldsRecord = table.fields || {}
    const primaryKeyFields = new Set(getPrimaryKeyFieldNames(table))

    return Object.values(fieldsRecord).sort((a, b) => {
        if (a.name === b.name) {
            return 0
        }

        const aIsPrimaryKey = primaryKeyFields.has(a.name)
        const bIsPrimaryKey = primaryKeyFields.has(b.name)

        if (aIsPrimaryKey !== bIsPrimaryKey) {
            return aIsPrimaryKey ? -1 : 1
        }

        return a.name.localeCompare(b.name)
    })
}

function getPrimaryKeyFieldNames(table: DatabaseSchemaTable): string[] {
    if (!('schema_metadata' in table)) {
        // find fields "id" or "uuid"
        return ['id', 'uuid', 'key', 'index'].filter((name) => name in table.fields)
    }

    const primaryKeyFromMetadata = table.schema_metadata?.primary_key || []
    if (primaryKeyFromMetadata.length) {
        return primaryKeyFromMetadata
    }

    const indexPrimaryKeys =
        table.schema_metadata?.indexes?.filter((index) => index.is_primary).flatMap((index) => index.columns) || []
    if (indexPrimaryKeys.length) {
        return indexPrimaryKeys
    }

    const isClickhouseTable =
        'format' in table && typeof table.format === 'string' && table.format.toLowerCase().includes('clickhouse')
    if (isClickhouseTable && table.fields?.id) {
        return ['id']
    }

    return []
}

function resolveFieldReference(
    field: DatabaseSchemaField,
    table: DatabaseSchemaTable,
    database: DatabaseSchemaQueryResponse | null
): { field: DatabaseSchemaField; table: DatabaseSchemaTable } {
    let currentField = field
    let currentTable = table

    for (const part of field.chain || []) {
        if (typeof part !== 'string') {
            break
        }

        const nextField = currentTable.fields?.[part]

        if (!nextField) {
            break
        }

        currentField = nextField

        if (nextField.table) {
            const nextTable = getTableFromDatabase(database, nextField.table)
            if (nextTable) {
                currentTable = nextTable
            }
        }
    }

    return { field: currentField, table: currentTable }
}

function filterFieldTreeNodes(nodes: FieldTreeNode[], term: string): FieldTreeNode[] {
    return nodes
        .map((node) => {
            const filteredChildren = filterFieldTreeNodes(node.children, term)
            const matches =
                fuzzyMatch(node.path, term) || fuzzyMatch(node.field.name, term) || filteredChildren.length > 0

            if (!matches) {
                return null
            }

            return { ...node, children: filteredChildren }
        })
        .filter(Boolean) as FieldTreeNode[]
}

function fuzzyMatch(value: string, term: string): boolean {
    const normalizedValue = value.toLowerCase()
    const tokens = term
        .toLowerCase()
        .split(/\s+/)
        .map((token) => token.trim())
        .filter(Boolean)

    if (!tokens.length) {
        return true
    }

    return tokens.every((token) => isSubsequence(normalizedValue, token))
}

function isSubsequence(target: string, query: string): boolean {
    let searchFromIndex = 0

    for (const character of query) {
        const foundIndex = target.indexOf(character, searchFromIndex)
        if (foundIndex === -1) {
            return false
        }
        searchFromIndex = foundIndex + 1
    }

    return true
}

function buildFieldTrees(
    table: DatabaseSchemaTable | null,
    database: DatabaseSchemaQueryResponse | null,
    searchTerm: string,
    expandedFields: string[]
): FieldTreeNode[] {
    if (!table) {
        return []
    }

    const visitedTables = new Set<string>([table.name])
    const nodes = buildFieldTreeNodes(table, database, '', visitedTables, new Set(expandedFields), !!searchTerm)

    if (!searchTerm) {
        return nodes
    }

    return filterFieldTreeNodes(nodes, searchTerm)
}

function getTableFromDatabase(
    database: DatabaseSchemaQueryResponse | null,
    tableName: string
): DatabaseSchemaTable | null {
    return (database as any)?.tables?.[tableName] || null
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

export function getTableDialect(table: DatabaseSchemaTable): 'postgres' | 'clickhouse' {
    return (table as any)?.source?.source_type === 'Postgres' ? 'postgres' : 'clickhouse'
}

function getTableSourceId(table: DatabaseSchemaTable): string | null {
    return (table as any)?.source?.id || null
}

function isDirectQueryTable(table: DatabaseSchemaTable): boolean {
    return (table as any)?.source?.is_direct_query === true
}
