import { actions, connect, kea, key, path, props, propsChanged, reducers, selectors } from 'kea'
import type { dataTableLogicType } from './dataTableLogicType'
import { AnyDataNode, DataTableNode, EventsQuery, HogQLExpression, NodeKind } from '~/queries/schema'
import { getColumnsForQuery, removeExpressionComment } from './utils'
import { objectsEqual, sortedKeys } from 'lib/utils'
import { isDataTableNode, isEventsQuery } from '~/queries/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { dayjs } from 'lib/dayjs'
import equal from 'fast-deep-equal'

export interface DataTableLogicProps {
    key: string
    query: DataTableNode
}

export const categoryRowKey = Symbol('__categoryRow__')
export const loadingColumn = Symbol('...')
export const errorColumn = Symbol('Error!')

export const dataTableLogic = kea<dataTableLogicType>([
    props({} as DataTableLogicProps),
    key((props) => {
        if (!props.key) {
            throw new Error('dataTableLogic must contain a key in props')
        }
        if (!isDataTableNode(props.query)) {
            throw new Error('dataTableLogic only accepts queries of type DataTableNode')
        }
        return props.key
    }),
    path(['queries', 'nodes', 'DataTable', 'dataTableLogic']),
    actions({ setColumnsInQuery: (columns: HogQLExpression[]) => ({ columns }) }),
    reducers(({ props }) => ({
        columnsInQuery: [getColumnsForQuery(props.query), { setColumnsInQuery: (_, { columns }) => columns }],
    })),
    connect((props: DataTableLogicProps) => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            dataNodeLogic({ key: props.key, query: props.query.source }),
            ['response', 'responseLoading', 'responseError', 'highlightedRows'],
        ],
    })),
    selectors({
        sourceKind: [(_, p) => [p.query], (query): NodeKind | null => query.source?.kind],
        orderBy: [
            (_, p) => [p.query],
            (query): string[] | null => (isEventsQuery(query.source) ? query.source.orderBy || ['-timestamp'] : null),
            { resultEqualityCheck: objectsEqual },
        ],
        columnsInResponse: [
            (s) => [s.response],
            (response: AnyDataNode['response']): string[] | null =>
                response &&
                'columns' in response &&
                Array.isArray(response.columns) &&
                !response.columns.find((c) => typeof c !== 'string')
                    ? (response?.columns as string[])
                    : null,
        ],
        columns: [
            (s) => [s.columnsInResponse, s.columnsInQuery],
            // always show columns in the query (what the user entered), and transform results to match below
            (columnsInResponse, columnsInQuery): string[] => columnsInQuery ?? columnsInResponse ?? [],
        ],
        resultsWithLabelRows: [
            (s) => [s.sourceKind, s.orderBy, s.response, s.columns, s.responseError],
            (sourceKind, orderBy, response: AnyDataNode['response'], columns, responseError): any[] | null => {
                if (response && sourceKind === NodeKind.EventsQuery) {
                    const eventsQueryResponse = response as EventsQuery['response'] | null
                    if (eventsQueryResponse) {
                        const { results, columns: columnsInResponse } = eventsQueryResponse
                        const orderKey = orderBy?.[0]?.startsWith('-') ? orderBy[0].slice(1) : orderBy?.[0]
                        const orderKeyIndex = columns.findIndex(
                            (column) =>
                                removeExpressionComment(column) === orderKey ||
                                removeExpressionComment(column) === `-${orderKey}`
                        )

                        // if we errored by adding a new column, show the new columns with the old results
                        // if the columns changed in any other way, return no results
                        if (
                            responseError &&
                            columnsInResponse &&
                            (columns.length <= columnsInResponse.length ||
                                columnsInResponse.find((c) => !columns.includes(c)))
                        ) {
                            return []
                        }

                        const columnMap = Object.fromEntries(columnsInResponse.map((c, i) => [c, i]))
                        const convertResultToDisplayedColumns = equal(columns, columnsInResponse)
                            ? (result: any[]) => result
                            : (result: any[]): any[] => {
                                  const newResult = columns.map((c) =>
                                      c in columnMap
                                          ? result[columnMap[c]]
                                          : responseError
                                          ? errorColumn
                                          : loadingColumn
                                  )
                                  ;(newResult as any).__originalResultRow = result
                                  return newResult
                              }

                        // Add a label between results if the day changed
                        if (orderKey === 'timestamp' && orderKeyIndex !== -1) {
                            let lastResult: any | null = null
                            const newResults: any[] = []
                            for (const result of results) {
                                if (
                                    result &&
                                    lastResult &&
                                    !dayjs(result[orderKeyIndex]).isSame(lastResult[orderKeyIndex], 'day')
                                ) {
                                    newResults.push({
                                        [categoryRowKey]: dayjs(result[orderKeyIndex]).format('LL'),
                                    })
                                }
                                newResults.push(convertResultToDisplayedColumns(result))
                                lastResult = result
                            }
                            return newResults
                        } else {
                            return results.map((result) => convertResultToDisplayedColumns(result))
                        }
                    }
                }
                return response && 'results' in response ? (response as any).results ?? null : null
            },
        ],
        isRowHighlighted: [
            (s) => [s.highlightedRows],
            (highlightedRows) =>
                (row: any[]): boolean =>
                    row
                        ? highlightedRows.has('__originalResultRow' in row ? (row as any).__originalResultRow : row)
                        : false,
        ],
        queryWithDefaults: [
            (s, p) => [p.query, s.columnsInQuery, s.featureFlags],
            (query: DataTableNode, columnsInQuery, featureFlags): Required<DataTableNode> => {
                const { kind, columns: _columns, source, ...rest } = query
                const showIfFull = !!query.full
                const flagQueryRunningTimeEnabled = featureFlags[FEATURE_FLAGS.QUERY_RUNNING_TIME]
                return {
                    kind,
                    columns: columnsInQuery,
                    hiddenColumns: [],
                    source,
                    ...sortedKeys({
                        ...rest,
                        full: query.full ?? false,
                        expandable: query.expandable ?? true,
                        propertiesViaUrl: query.propertiesViaUrl ?? false,
                        showPropertyFilter: query.showPropertyFilter ?? showIfFull,
                        showEventFilter: query.showEventFilter ?? showIfFull,
                        showSearch: query.showSearch ?? showIfFull,
                        showActions: query.showActions ?? true,
                        showDateRange: query.showDateRange ?? showIfFull,
                        showExport: query.showExport ?? showIfFull,
                        showReload: query.showReload ?? showIfFull,
                        showElapsedTime: query.showElapsedTime ?? (flagQueryRunningTimeEnabled ? showIfFull : false),
                        showColumnConfigurator: query.showColumnConfigurator ?? showIfFull,
                        showEventsBufferWarning: query.showEventsBufferWarning ?? showIfFull,
                        allowSorting: query.allowSorting ?? true,
                    }),
                }
            },
        ],
        canSort: [
            (s) => [s.queryWithDefaults],
            (query: DataTableNode): boolean => isEventsQuery(query.source) && !!query.allowSorting,
        ],
    }),
    propsChanged(({ actions, props }, oldProps) => {
        const newColumns = getColumnsForQuery(props.query)
        const oldColumns = getColumnsForQuery(oldProps.query)
        if (JSON.stringify(newColumns) !== JSON.stringify(oldColumns)) {
            actions.setColumnsInQuery(newColumns)
        }
    }),
])
