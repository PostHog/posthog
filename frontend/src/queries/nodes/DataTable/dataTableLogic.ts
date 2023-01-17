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

export interface DataTableLogicProps {
    key: string
    query: DataTableNode
}

export const categoryRowKey = Symbol('__categoryRow__')

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
            ['response', 'responseLoading'],
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
        resultsWithLabelRows: [
            (s) => [s.sourceKind, s.orderBy, s.response, s.columnsInResponse, s.columnsInQuery],
            (sourceKind, orderBy, response, columnsInResponse, columnsInQuery): any[] | null => {
                if (sourceKind === NodeKind.EventsQuery) {
                    const results = (response as EventsQuery['response'] | null)?.results
                    if (results) {
                        const orderKey = orderBy?.[0]?.startsWith('-') ? orderBy[0].slice(1) : orderBy?.[0]
                        const orderKeyIndex = (columnsInResponse ?? columnsInQuery).findIndex(
                            (column) =>
                                removeExpressionComment(column) === orderKey ||
                                removeExpressionComment(column) === `-${orderKey}`
                        )

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
                                newResults.push(result)
                                lastResult = result
                            }
                            return newResults
                        }
                    }
                }
                return response && 'results' in response ? (response as any).results ?? null : null
            },
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
