import equal from 'fast-deep-equal'
import { actions, connect, kea, key, path, props, propsChanged, reducers, selectors } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { objectsEqual, sortedKeys } from 'lib/utils'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { QueryFeature, getQueryFeatures } from '~/queries/nodes/DataTable/queryFeatures'
import { insightVizDataCollectionId } from '~/queries/nodes/InsightViz/InsightViz'
import {
    AnyDataNode,
    AnyResponseType,
    DataTableNode,
    EventsQuery,
    HogQLExpression,
    NodeKind,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'
import { isDataTableNode, isEventsQuery } from '~/queries/utils'
import { RequiredExcept } from '~/types'

import type { dataTableLogicType } from './dataTableLogicType'
import { getColumnsForQuery, removeExpressionComment } from './utils'

export interface DataTableLogicProps {
    vizKey: string
    dataKey: string
    query: DataTableNode
    context?: QueryContext<DataTableNode>
    // Override the data logic node key if needed
    dataNodeLogicKey?: string
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
            dataNodeLogic({
                key: props.dataNodeLogicKey ?? props.dataKey,
                query: props.query.source,
                dataNodeCollectionId: insightVizDataCollectionId(
                    props.context?.insightProps,
                    props.dataNodeLogicKey ?? props.dataKey
                ),
                loadPriority: props.context?.insightProps?.loadPriority,
            }),
            ['response', 'responseLoading', 'responseError'],
        ],
    })),
    selectors({
        sourceKind: [(_, p) => [p.query], (query): NodeKind | null => query.source?.kind],
        sourceFeatures: [
            (_, p) => [p.query, (_, props) => props.context],
            (query, context): Set<QueryFeature> => {
                const sourceFeatures = getQueryFeatures(query.source)
                if (context?.extraDataTableQueryFeatures) {
                    for (const feature of context.extraDataTableQueryFeatures) {
                        sourceFeatures.add(feature)
                    }
                }
                return sourceFeatures
            },
        ],
        orderBy: [
            (s, p) => [p.query, s.sourceFeatures],
            (query, sourceFeatures): string[] | null =>
                sourceFeatures.has(QueryFeature.selectAndOrderByColumns)
                    ? 'orderBy' in query.source // might not be EventsQuery, but something else with orderBy
                        ? ((query.source as EventsQuery).orderBy ?? null)
                        : isEventsQuery(query.source)
                          ? ['timestamp DESC']
                          : null
                    : null,
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
                if (response && (sourceKind === NodeKind.EventsQuery || sourceKind === NodeKind.SessionsQuery)) {
                    const queryResponse = response as AnyResponseType
                    if (queryResponse) {
                        // must be loading
                        if (!equal(columnsInQuery, columnsInResponse)) {
                            return []
                        }

                        let results: any[] | null = []
                        if ('results' in queryResponse) {
                            results = queryResponse.results
                        } else if ('result' in queryResponse) {
                            results = queryResponse.result
                        }

                        if (!results) {
                            return []
                        }

                        const orderKey = orderBy?.[0]?.endsWith(' DESC')
                            ? orderBy[0].replace(/ DESC$/, '')
                            : orderBy?.[0]
                        const orderKeyIndex =
                            columnsInResponse?.findIndex(
                                (column) =>
                                    removeExpressionComment(column) === orderKey ||
                                    removeExpressionComment(column) === `-${orderKey}`
                            ) ?? -1

                        // Add a label between results if the day changed (for events with timestamp, or sessions with $start_timestamp)
                        if ((orderKey === 'timestamp' || orderKey === '$start_timestamp') && orderKeyIndex !== -1) {
                            let lastResult: any = null
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
                        }
                        return results.map((result) => ({ result }))
                    }
                }

                const results = !response
                    ? null
                    : 'results' in response && Array.isArray(response.results)
                      ? response.results
                      : 'result' in response && Array.isArray(response.result)
                        ? response.result
                        : null

                return results ? (results.map((result: any) => ({ result })) ?? null) : null
            },
        ],
        queryWithDefaults: [
            (s, p) => [p.query, s.columnsInQuery, s.featureFlags, (_, props) => props.context],
            (
                query: DataTableNode,
                columnsInQuery,
                featureFlags,
                context
            ): RequiredExcept<Omit<DataTableNode, 'response'>, 'version' | 'tags' | 'defaultColumns'> => {
                const { kind, columns: _columns, source, ...rest } = query
                const showIfFull = !!query.full
                const flagQueryRunningTimeEnabled = !!featureFlags[FEATURE_FLAGS.QUERY_RUNNING_TIME]
                const flagQueryTimingsEnabled = !!featureFlags[FEATURE_FLAGS.QUERY_TIMINGS]
                return {
                    kind,
                    columns: columnsInQuery,
                    hiddenColumns: [],
                    pinnedColumns: query.pinnedColumns ?? [],
                    source,
                    context: query.context ?? { type: 'team_columns' },
                    ...sortedKeys({
                        ...rest,
                        full: query.full ?? false,

                        // The settings under features.tsx override some of these
                        expandable: query.expandable ?? true,
                        embedded: query.embedded ?? false,
                        propertiesViaUrl: query.propertiesViaUrl ?? false,
                        showPropertyFilter: query.showPropertyFilter ?? showIfFull,
                        showEventFilter: query.showEventFilter ?? showIfFull,
                        showSearch: query.showSearch ?? showIfFull,
                        showActions: query.showActions ?? true,
                        showDateRange: query.showDateRange ?? showIfFull,
                        showTestAccountFilters: query.showTestAccountFilters ?? showIfFull,
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
                        showSavedFilters: query.showSavedFilters ?? false,
                        showHogQLEditor: query.showHogQLEditor ?? showIfFull,
                        allowSorting: query.allowSorting ?? true,
                        showOpenEditorButton:
                            context?.showOpenEditorButton !== undefined
                                ? context.showOpenEditorButton
                                : (query.showOpenEditorButton ?? true),
                        showResultsTable: query.showResultsTable ?? true,
                    }),
                }
            },
        ],
        canSort: [
            (s) => [s.queryWithDefaults, s.sourceFeatures],
            (query: DataTableNode, sourceFeatures): boolean =>
                sourceFeatures.has(QueryFeature.selectAndOrderByColumns) && !!query.allowSorting,
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
