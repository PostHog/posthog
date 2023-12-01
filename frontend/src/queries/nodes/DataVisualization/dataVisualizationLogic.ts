import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AnyResponseType, DataVisualizationNode } from '~/queries/schema'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType, ItemMode } from '~/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'
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
        values: [teamLogic, ['currentTeamId'], insightSceneLogic, ['insightMode'], dataNodeLogic, ['response']],
        actions: [dataNodeLogic, ['loadDataSuccess']],
    }),
    props({ query: {} } as DataVisualizationLogicProps),
    actions({
        setVisualizationType: (visualizationType: ChartDisplayType) => ({ visualizationType }),
        setXAxis: (columnIndex: number) => ({ selectedXAxisColumnIndex: columnIndex }),
        setYAxis: (columnIndex: number) => ({ selectedYAxisColumnIndex: columnIndex }),
        clearAxis: true,
        setQuery: (node: DataVisualizationNode) => ({ node }),
    }),
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
    listeners(({ props }) => ({
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
