import { actions, afterMount, connect, kea, listeners, path, props, propsChanged, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { objectsEqual, shouldCancelQuery, uuid } from 'lib/utils'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { teamLogic } from 'scenes/teamLogic'

import { query } from '~/queries/query'
import { AnyResponseType, DataVisualizationNode } from '~/queries/schema'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType, ItemMode } from '~/types'

import type { dataVisualizationLogicType } from './dataVisualizationLogicType'

export interface DataVisualizationLogicProps {
    key: string
    query: DataVisualizationNode
    context?: QueryContext
    setQuery?: (node: DataVisualizationNode) => void
    cachedResults?: AnyResponseType
}

export const dataVisualizationLogic = kea<dataVisualizationLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'dataVisualizationLogic']),
    connect({
        values: [teamLogic, ['currentTeamId'], insightSceneLogic, ['insightMode']],
    }),
    props({ query: {} } as DataVisualizationLogicProps),
    propsChanged(({ actions, props }, oldProps) => {
        if (!props.query) {
            return // Can't do anything without a query
        }
        if (oldProps.query && props.query.kind !== oldProps.query.kind) {
            actions.clearResponse()
        }
        if (!objectsEqual(props.query, oldProps.query)) {
            if (!props.cachedResults || (!props.cachedResults['result'] && !props.cachedResults['results'])) {
                actions.loadData()
            } else {
                actions.setResponse(props.cachedResults)
            }
        }
    }),
    actions({
        loadData: (refresh = false) => ({ refresh, queryId: uuid() }),
        setResponse: (response: Exclude<AnyResponseType, undefined>) => response,
        clearResponse: true,
        abortQuery: (payload: { queryId: string }) => payload,
        cancelQuery: true,
        setElapsedTime: (elapsedTime: number) => ({ elapsedTime }),
        setVisualizationType: (visualizationType: ChartDisplayType) => ({ visualizationType }),
        setXAxis: (columnIndex: number) => ({ selectedXAxisColumnIndex: columnIndex }),
        setYAxis: (columnIndex: number) => ({ selectedYAxisColumnIndex: columnIndex }),
        clearAxis: true,
        setQuery: (node: DataVisualizationNode) => ({ node }),
    }),
    loaders(({ props, actions, cache }) => ({
        response: [
            props.cachedResults ?? null,
            {
                setResponse: (response) => response,
                clearResponse: () => null,
                loadData: async ({ refresh, queryId }, breakpoint) => {
                    const now = performance.now()
                    try {
                        cache.abortController = new AbortController()
                        const data =
                            (await query<DataVisualizationNode>(
                                props.query,
                                { signal: cache.abortController.signal },
                                refresh,
                                queryId
                            )) ?? null
                        breakpoint()
                        actions.setElapsedTime(performance.now() - now)
                        return data
                    } catch (e: any) {
                        actions.setElapsedTime(performance.now() - now)
                        if (shouldCancelQuery(e)) {
                            actions.abortQuery({ queryId })
                        }
                        breakpoint()
                        e.queryId = queryId
                        throw e
                    }
                },
            },
        ],
    })),
    reducers({
        columns: [
            [] as { name: string; type: string }[],
            {
                loadDataSuccess: (_state, { response }) => {
                    if (!response) {
                        return []
                    }

                    const columns: string[] = response['columns']
                    const types: string[][] = response['types']

                    return columns.map((column, index) => {
                        const type = types[index][1]
                        return {
                            name: column,
                            type,
                        }
                    })
                },
            },
        ],
        loadingStart: [
            null as number | null,
            {
                setElapsedTime: () => null,
                loadData: () => performance.now(),
            },
        ],
        elapsedTime: [
            null as number | null,
            {
                setElapsedTime: (_, { elapsedTime }) => elapsedTime,
                loadData: () => null,
            },
        ],
        responseError: [
            null as string | null,
            {
                loadData: () => null,
                loadDataFailure: (_, { error, errorObject }) => {
                    if (errorObject && 'error' in errorObject) {
                        return errorObject.error
                    }
                    if (errorObject && 'detail' in errorObject) {
                        return errorObject.detail
                    }
                    return error ?? 'Error loading data'
                },
                loadDataSuccess: () => null,
            },
        ],
        visualizationType: [
            ChartDisplayType.ActionsTable as ChartDisplayType,
            {
                setVisualizationType: (_, { visualizationType }) => visualizationType,
            },
        ],
        selectedXIndex: [
            null as number | null,
            {
                clearAxis: () => null,
                setXAxis: (_, { selectedXAxisColumnIndex }) => selectedXAxisColumnIndex,
            },
        ],
        selectedYIndex: [
            null as number | null,
            {
                clearAxis: () => null,
                setYAxis: (_, { selectedYAxisColumnIndex }) => selectedYAxisColumnIndex,
            },
        ],
    }),
    selectors({
        query: [(_state, props) => [props.query], (query) => query],
        showEditingUI: [(state) => [state.insightMode], (insightMode) => insightMode == ItemMode.Edit],
        isShowingCachedResults: [
            () => [(_, props) => props.cachedResults ?? null],
            (cachedResults: AnyResponseType | null): boolean => !!cachedResults,
        ],
        yData: [
            (state) => [state.selectedYIndex, state.response],
            (yIndex, response): null | number[] => {
                if (!response || yIndex === null) {
                    return null
                }

                const data: any[] = response?.['results'] ?? []
                return data.map((n) => {
                    try {
                        return parseInt(n[yIndex], 10)
                    } catch {
                        return 0
                    }
                })
            },
        ],
        xData: [
            (state) => [state.selectedXIndex, state.response],
            (xIndex, response): null | string[] => {
                if (!response || xIndex === null) {
                    return null
                }

                const data: any[] = response?.['results'] ?? []
                return data.map((n) => n[xIndex])
            },
        ],
    }),
    listeners(({ values, cache, props }) => ({
        abortQuery: async ({ queryId }) => {
            try {
                const { currentTeamId } = values
                await api.delete(`api/projects/${currentTeamId}/query/${queryId}/`)
            } catch (e) {
                console.warn('Failed cancelling query', e)
            }
        },
        cancelQuery: () => {
            if (cache.abortController) {
                cache.abortController.abort()
                cache.abortController = null
            }
        },
        setQuery: ({ node }) => {
            if (props.setQuery) {
                props.setQuery(node)
            }
        },
        setVisualizationType: ({ visualizationType }) => {
            if (props.setQuery) {
                props.setQuery({
                    ...props.query,
                    display: visualizationType,
                })
            }
        },
        setXAxis: ({ selectedXAxisColumnIndex }) => {
            if (props.setQuery) {
                props.setQuery({
                    ...props.query,
                    chartSettings: {
                        ...(props.query.chartSettings ?? {}),
                        xAxisIndex: [selectedXAxisColumnIndex],
                    },
                })
            }
        },
        setYAxis: ({ selectedYAxisColumnIndex }) => {
            if (props.setQuery) {
                props.setQuery({
                    ...props.query,
                    chartSettings: {
                        ...(props.query.chartSettings ?? {}),
                        yAxisIndex: [selectedYAxisColumnIndex],
                    },
                })
            }
        },
    })),
    afterMount(({ actions, props }) => {
        if (Object.keys(props.query || {}).length > 0) {
            actions.loadData()
        }

        if (props.query.display) {
            actions.setVisualizationType(props.query.display)
        }

        if (props.query.chartSettings) {
            const { xAxisIndex, yAxisIndex } = props.query.chartSettings

            if (xAxisIndex && xAxisIndex.length) {
                actions.setXAxis(xAxisIndex[0])
            }

            if (yAxisIndex && yAxisIndex.length) {
                actions.setYAxis(yAxisIndex[0])
            }
        }
    }),
    subscriptions(({ actions }) => ({
        columns: (value, oldValue) => {
            if (!oldValue || !oldValue.length) {
                return
            }

            if (JSON.stringify(value) !== JSON.stringify(oldValue)) {
                actions.clearAxis()
            }
        },
    })),
])
