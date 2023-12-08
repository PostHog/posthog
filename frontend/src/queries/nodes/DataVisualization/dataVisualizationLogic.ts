import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { teamLogic } from 'scenes/teamLogic'

import { AnyResponseType, DataVisualizationNode } from '~/queries/schema'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType, InsightLogicProps, ItemMode } from '~/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { getQueryFeatures, QueryFeature } from '../DataTable/queryFeatures'
import type { dataVisualizationLogicType } from './dataVisualizationLogicType'

export interface AxisSeries<T> {
    name: string
    data: T[]
}

export interface DataVisualizationLogicProps {
    key: string
    query: DataVisualizationNode
    insightLogicProps: InsightLogicProps
    context?: QueryContext
    setQuery?: (node: DataVisualizationNode) => void
    cachedResults?: AnyResponseType
}

export const dataVisualizationLogic = kea<dataVisualizationLogicType>([
    key((props) => props.key),
    path(['queries', 'nodes', 'DataVisualization', 'dataVisualizationLogic']),
    connect({
        values: [teamLogic, ['currentTeamId'], insightSceneLogic, ['insightMode'], dataNodeLogic, ['response']],
        actions: [dataNodeLogic, ['loadDataSuccess']],
    }),
    props({ query: {} } as DataVisualizationLogicProps),
    actions({
        setVisualizationType: (visualizationType: ChartDisplayType) => ({ visualizationType }),
        updateXSeries: (columnIndex: number) => ({
            selectedXSeriesColumnIndex: columnIndex,
        }),
        updateYSeries: (seriesIndex: number, columnIndex: number) => ({
            seriesIndex,
            selectedYSeriesColumnIndex: columnIndex,
        }),
        addYSeries: (columnIndex?: number) => ({ columnIndex }),
        deletedYSeries: (seriesIndex: number) => ({ seriesIndex }),
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
                updateXSeries: (_, { selectedXSeriesColumnIndex }) => selectedXSeriesColumnIndex,
            },
        ],
        selectedYIndexes: [
            null as (number | null)[] | null,
            {
                clearAxis: () => null,
                addYSeries: (prev, { columnIndex }) => {
                    if (!prev && columnIndex !== undefined) {
                        return [columnIndex]
                    }

                    if (!prev) {
                        return [null]
                    }

                    prev.push(columnIndex === undefined ? null : columnIndex)
                    return [...prev]
                },
                updateYSeries: (prev, { seriesIndex, selectedYSeriesColumnIndex }) => {
                    if (!prev) {
                        return null
                    }

                    prev[seriesIndex] = selectedYSeriesColumnIndex
                    return [...prev]
                },
                deletedYSeries: (prev, { seriesIndex }) => {
                    if (!prev) {
                        return null
                    }

                    if (prev.length <= 1) {
                        return [null]
                    }

                    prev.splice(seriesIndex, 1)

                    return [...prev]
                },
            },
        ],
    }),
    selectors({
        query: [(_state, props) => [props.query], (query) => query],
        showEditingUI: [
            (state, props) => [state.insightMode, props.insightLogicProps],
            (insightMode, insightLogicProps) => {
                if (insightLogicProps.dashboardId) {
                    return false
                }

                return insightMode == ItemMode.Edit
            },
        ],
        showResultControls: [
            (state, props) => [state.insightMode, props.insightLogicProps],
            (insightMode, insightLogicProps) => {
                if (insightMode === ItemMode.Edit) {
                    return true
                }

                return !insightLogicProps.dashboardId
            },
        ],
        presetChartHeight: [
            (_state, props) => [props.insightLogicProps],
            (insightLogicProps) => {
                return !insightLogicProps.dashboardId
            },
        ],
        sourceFeatures: [(_, props) => [props.query], (query): Set<QueryFeature> => getQueryFeatures(query.source)],
        isShowingCachedResults: [
            () => [(_, props) => props.cachedResults ?? null],
            (cachedResults: AnyResponseType | null): boolean => !!cachedResults,
        ],
        yData: [
            (state) => [state.selectedYIndexes, state.response],
            (yIndexes, response): null | AxisSeries<number>[] => {
                if (!response || yIndexes === null || yIndexes.length === 0) {
                    return null
                }

                const data: any[] = response?.['results'] ?? []
                const columns: string[] = response['columns']

                return yIndexes
                    .filter((n): n is number => Boolean(n))
                    .map((index): AxisSeries<number> => {
                        return {
                            name: columns[index],
                            data: data.map((n) => {
                                try {
                                    return parseInt(n[index], 10)
                                } catch {
                                    return 0
                                }
                            }),
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
    })),
    afterMount(({ actions, props }) => {
        if (props.query.display) {
            actions.setVisualizationType(props.query.display)
        }

        if (props.query.chartSettings) {
            const { xAxisIndex, yAxisIndex } = props.query.chartSettings

            if (xAxisIndex && xAxisIndex.length) {
                actions.updateXSeries(xAxisIndex[0])
            }

            if (yAxisIndex && yAxisIndex.length) {
                yAxisIndex.forEach((index) => {
                    actions.addYSeries(index)
                })
            }
        }
    }),
    subscriptions(({ props, actions, values }) => ({
        columns: (value: { name: string; type: string }[], oldValue: { name: string; type: string }[]) => {
            if (oldValue && oldValue.length) {
                if (JSON.stringify(value) !== JSON.stringify(oldValue)) {
                    actions.clearAxis()
                }
            }

            // Set default axis values
            if (values.response && values.selectedXIndex === null && values.selectedYIndexes === null) {
                const types: string[][] = values.response['types']
                const yAxisIndex = types.findIndex((n) => n[1].indexOf('Int') !== -1 || n[1].indexOf('Float') !== -1)
                const xAxisIndex = types.findIndex((n) => n[1].indexOf('Date') !== -1)

                if (yAxisIndex >= 0) {
                    actions.addYSeries(yAxisIndex)
                }

                if (xAxisIndex >= 0) {
                    actions.updateXSeries(xAxisIndex)
                }
            }
        },
        selectedXIndex: (value: number | null) => {
            if (props.setQuery) {
                props.setQuery({
                    ...props.query,
                    chartSettings: {
                        ...(props.query.chartSettings ?? {}),
                        yAxisIndex: values.selectedYIndexes?.filter((n: number | null): n is number => Boolean(n)),
                        xAxisIndex: value !== null ? [value] : undefined,
                    },
                })
            }
        },
        selectedYIndexes: (value: (number | null)[] | null) => {
            if (props.setQuery) {
                props.setQuery({
                    ...props.query,
                    chartSettings: {
                        ...(props.query.chartSettings ?? {}),
                        yAxisIndex: value?.filter((n: number | null): n is number => Boolean(n)),
                        xAxisIndex: values.selectedXIndex !== null ? [values.selectedXIndex] : undefined,
                    },
                })
            }
        },
    })),
])
