import { actions, connect, kea, key, path, props, propsChanged, reducers, selectors } from 'kea'
import type { dataTableLogicType } from './dataTableLogicType'
import {
    AnyDataNode,
    DataTableNode,
    EventsQuery,
    HogQLExpression,
    NodeKind,
    QueryContext,
    TimeToSeeDataSessionsQuery,
} from '~/queries/schema'
import { getColumnsForQuery, removeExpressionComment } from './utils'
import { objectsEqual, sortedKeys } from 'lib/utils'
import { isDataTableNode, isEventsQuery } from '~/queries/utils'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { dayjs } from 'lib/dayjs'
import equal from 'fast-deep-equal'

export interface DataTableLogicProps {
    vizKey: string
    dataKey: string
    query: DataTableNode
    context?: QueryContext
}

export interface DataTableRow {
    /** Display a row with a label. */
    label?: JSX.Element | string | null
    /** Display a row with results */
    result?: Record<string, any> | any[]
}

export const loadingColumn = Symbol('...')
export const errorColumn = Symbol('Error!')

export const dataTableLogic = kea<dataTableLogicType>([
    props({} as DataTableLogicProps),
    key((props) => {
        if (!props.vizKey) {
            throw new Error('dataTableLogic must contain a vizKey in props')
        }
        if (!isDataTableNode(props.query)) {
            throw new Error('dataTableLogic only accepts queries of type DataTableNode')
        }
        return props.vizKey
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
            dataNodeLogic({ key: props.dataKey, query: props.query.source }),
            ['response', 'responseLoading', 'responseError'],
        ],
    })),
    selectors({
        sourceKind: [(_, p) => [p.query], (query): NodeKind | null => query.source?.kind],
        orderBy: [
            (_, p) => [p.query],
            (query): string[] | null =>
                isEventsQuery(query.source) ? query.source.orderBy || ['timestamp DESC'] : null,
            { resultEqualityCheck: objectsEqual },
        ],
        columnsInResponse: [
            (s) => [s.response],
            (response: AnyDataNode['response']): string[] | null =>
                response && 'columns' in response && Array.isArray(response.columns) ? response?.columns : null,
        ],
        dataTableRows: [
            (s) => [s.sourceKind, s.orderBy, s.response, s.columnsInQuery, s.columnsInResponse],
            (
                sourceKind,
                orderBy,
                response: AnyDataNode['response'],
                columnsInQuery,
                columnsInResponse
            ): DataTableRow[] | null => {
                if (response && sourceKind === NodeKind.EventsQuery) {
                    const eventsQueryResponse = response as EventsQuery['response'] | null
                    if (eventsQueryResponse) {
                        // must be loading
                        if (!equal(columnsInQuery, columnsInResponse)) {
                            return []
                        }

                        const { results } = eventsQueryResponse
                        const orderKey = orderBy?.[0]?.endsWith(' DESC')
                            ? orderBy[0].replace(/ DESC$/, '')
                            : orderBy?.[0]
                        const orderKeyIndex =
                            columnsInResponse?.findIndex(
                                (column) =>
                                    removeExpressionComment(column) === orderKey ||
                                    removeExpressionComment(column) === `-${orderKey}`
                            ) ?? -1

                        // Add a label between results if the day changed
                        if (orderKey === 'timestamp' && orderKeyIndex !== -1) {
                            let lastResult: any | null = null
                            const newResults: DataTableRow[] = []
                            for (const result of results) {
                                if (
                                    result &&
                                    lastResult &&
                                    !dayjs(result[orderKeyIndex]).isSame(lastResult[orderKeyIndex], 'day')
                                ) {
                                    newResults.push({
                                        label: dayjs(result[orderKeyIndex]).format('LL'),
                                    })
                                }
                                newResults.push({ result })
                                lastResult = result
                            }
                            return newResults
                        } else {
                            return results.map((result) => ({ result }))
                        }
                    }
                }

                if (response && sourceKind === NodeKind.TimeToSeeDataSessionsQuery) {
                    return (response as NonNullable<TimeToSeeDataSessionsQuery['response']>).results.map((row) => ({
                        result: row,
                    }))
                }

                return response && 'results' in response && Array.isArray(response.results)
                    ? response.results.map((result: any) => ({ result })) ?? null
                    : null
            },
        ],
        queryWithDefaults: [
            (s, p) => [p.query, s.columnsInQuery, s.featureFlags, (_, props) => props.context],
            (query: DataTableNode, columnsInQuery, featureFlags, context): Required<DataTableNode> => {
                const { kind, columns: _columns, source, ...rest } = query
                const showIfFull = !!query.full
                const flagQueryRunningTimeEnabled = !!featureFlags[FEATURE_FLAGS.QUERY_RUNNING_TIME]
                const flagQueryTimingsEnabled = !!featureFlags[FEATURE_FLAGS.QUERY_TIMINGS]
                return {
                    kind,
                    columns: columnsInQuery,
                    hiddenColumns: [],
                    source,
                    ...sortedKeys({
                        ...rest,
                        full: query.full ?? false,
                        expandable: query.expandable ?? true,
                        embedded: query.embedded ?? false,
                        propertiesViaUrl: query.propertiesViaUrl ?? false,
                        showPropertyFilter: query.showPropertyFilter ?? showIfFull,
                        showEventFilter: query.showEventFilter ?? showIfFull,
                        showSearch: query.showSearch ?? showIfFull,
                        showActions: query.showActions ?? true,
                        showDateRange: query.showDateRange ?? showIfFull,
                        showExport: query.showExport ?? showIfFull,
                        showReload: query.showReload ?? showIfFull,
                        showTimings: query.showTimings ?? flagQueryTimingsEnabled,
                        showElapsedTime:
                            (query.showTimings ?? flagQueryTimingsEnabled) ||
                            (query.showElapsedTime ??
                                ((flagQueryRunningTimeEnabled || source.kind === NodeKind.HogQLQuery) && showIfFull)),
                        showColumnConfigurator: query.showColumnConfigurator ?? showIfFull,
                        showPersistentColumnConfigurator: query.showPersistentColumnConfigurator ?? false,
                        showSavedQueries: query.showSavedQueries ?? false,
                        showHogQLEditor: query.showHogQLEditor ?? showIfFull,
                        allowSorting: query.allowSorting ?? true,
                        showOpenEditorButton:
                            context?.showOpenEditorButton !== undefined
                                ? context.showOpenEditorButton
                                : query.showOpenEditorButton ?? true,
                        showResultsTable: query.showResultsTable ?? true,
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
