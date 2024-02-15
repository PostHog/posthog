import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { teamLogic } from 'scenes/teamLogic'

import { insightVizDataCollectionId } from '~/queries/nodes/InsightViz/InsightViz'
import { AnyResponseType, ChartAxis, DataVisualizationNode } from '~/queries/schema'
import { QueryContext } from '~/queries/types'
import { ChartDisplayType, InsightLogicProps, ItemMode } from '~/types'

import { dataNodeLogic } from '../DataNode/dataNodeLogic'
import { getQueryFeatures, QueryFeature } from '../DataTable/queryFeatures'
import type { dataVisualizationLogicType } from './dataVisualizationLogicType'

export enum SideBarTab {
    Series = 'series',
    Display = 'display',
}

export interface Column {
    name: string
    type: string
    label: string
    dataIndex: number
}

export interface AxisSeries<T> {
    column: Column
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
    connect((props: DataVisualizationLogicProps) => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            insightSceneLogic,
            ['insightMode'],
            dataNodeLogic({
                cachedResults: props.cachedResults,
                key: props.key,
                query: props.query.source,
                dataNodeCollectionId: insightVizDataCollectionId(props.insightLogicProps, props.key),
                loadPriority: props.insightLogicProps.loadPriority,
            }),
            ['response', 'responseLoading'],
        ],
        actions: [
            dataNodeLogic({
                cachedResults: props.cachedResults,
                key: props.key,
                query: props.query.source,
                dataNodeCollectionId: insightVizDataCollectionId(props.insightLogicProps, props.key),
                loadPriority: props.insightLogicProps.loadPriority,
            }),
            ['loadDataSuccess'],
        ],
    })),
    props({ query: {} } as DataVisualizationLogicProps),
    actions({
        setVisualizationType: (visualizationType: ChartDisplayType) => ({ visualizationType }),
        updateXSeries: (columnName: string) => ({
            columnName,
        }),
        updateYSeries: (seriesIndex: number, columnName: string) => ({
            seriesIndex,
            columnName,
        }),
        addYSeries: (columnName?: string) => ({ columnName }),
        deleteYSeries: (seriesIndex: number) => ({ seriesIndex }),
        clearAxis: true,
        setQuery: (node: DataVisualizationNode) => ({ node }),
        setSideBarTab: (tab: SideBarTab) => ({ tab }),
    }),
    reducers({
        columns: [
            [] as Column[],
            {
                loadDataSuccess: (_state, { response }) => {
                    if (!response) {
                        return []
                    }

                    const columns: string[] = response['columns'] ?? []
                    const types: string[][] = response['types'] ?? []

                    return columns.map((column, index) => {
                        const type = types[index]?.[1]
                        return {
                            name: column,
                            type,
                            label: `${column} - ${type}`,
                            dataIndex: index,
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
        selectedXAxis: [
            null as string | null,
            {
                clearAxis: () => null,
                updateXSeries: (_, { columnName }) => columnName,
            },
        ],
        selectedYAxis: [
            null as (string | null)[] | null,
            {
                clearAxis: () => null,
                addYSeries: (state, { columnName }) => {
                    if (!state && columnName !== undefined) {
                        return [columnName]
                    }

                    if (!state) {
                        return [null]
                    }

                    return [...state, columnName === undefined ? null : columnName]
                },
                updateYSeries: (state, { seriesIndex, columnName }) => {
                    if (!state) {
                        return null
                    }

                    const ySeries = [...state]

                    ySeries[seriesIndex] = columnName
                    return ySeries
                },
                deleteYSeries: (state, { seriesIndex }) => {
                    if (!state) {
                        return null
                    }

                    if (state.length <= 1) {
                        return [null]
                    }

                    const ySeries = [...state]

                    ySeries.splice(seriesIndex, 1)

                    return ySeries
                },
            },
        ],
        activeSideBarTab: [
            SideBarTab.Series as SideBarTab,
            {
                setSideBarTab: (_state, { tab }) => tab,
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
            (state) => [state.selectedYAxis, state.response, state.columns],
            (ySeries, response, columns): null | AxisSeries<number>[] => {
                if (!response || ySeries === null || ySeries.length === 0) {
                    return null
                }

                const data: any[] = response?.['results'] ?? []

                return ySeries
                    .map((name): AxisSeries<number> | null => {
                        if (!name) {
                            return {
                                column: {
                                    name: 'None',
                                    type: 'None',
                                    label: 'None',
                                    dataIndex: -1,
                                },
                                data: [],
                            }
                        }

                        const column = columns.find((n) => n.name === name)
                        if (!column) {
                            return null
                        }

                        return {
                            column,
                            data: data.map((n) => {
                                try {
                                    return parseInt(n[column.dataIndex], 10)
                                } catch {
                                    return 0
                                }
                            }),
                        }
                    })
                    .filter((series): series is AxisSeries<number> => Boolean(series))
            },
        ],
        xData: [
            (state) => [state.selectedXAxis, state.response, state.columns],
            (xSeries, response, columns): AxisSeries<string> | null => {
                if (!response || xSeries === null) {
                    return {
                        column: {
                            name: 'None',
                            type: 'None',
                            label: 'None',
                            dataIndex: -1,
                        },
                        data: [],
                    }
                }

                const data: any[] = response?.['results'] ?? []

                const column = columns.find((n) => n.name === xSeries)
                if (!column) {
                    return null
                }

                return {
                    column,
                    data: data.map((n) => n[column.dataIndex]),
                }
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
            const { xAxis, yAxis } = props.query.chartSettings

            if (xAxis) {
                actions.updateXSeries(xAxis.column)
            }

            if (yAxis && yAxis.length) {
                yAxis.forEach((axis) => {
                    actions.addYSeries(axis.column)
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
            if (values.response && values.selectedXAxis === null && values.selectedYAxis === null) {
                const types: string[][] = values.response['types']
                const yAxisTypes = types.find((n) => n[1].indexOf('Int') !== -1 || n[1].indexOf('Float') !== -1)
                const xAxisTypes = types.find((n) => n[1].indexOf('Date') !== -1)

                if (yAxisTypes) {
                    actions.addYSeries(yAxisTypes[0])
                }

                if (xAxisTypes) {
                    actions.updateXSeries(xAxisTypes[0])
                }
            }
        },
        selectedXAxis: (value: string | null) => {
            if (props.setQuery) {
                const yColumns = values.selectedYAxis?.filter((n: string | null): n is string => Boolean(n)) ?? []
                const xColumn: ChartAxis | undefined = value !== null ? { column: value } : undefined

                props.setQuery({
                    ...props.query,
                    chartSettings: {
                        ...(props.query.chartSettings ?? {}),
                        yAxis: yColumns.map((n) => ({ column: n })),
                        xAxis: xColumn,
                    },
                })
            }
        },
        selectedYAxis: (value: (string | null)[] | null) => {
            if (props.setQuery) {
                const yColumns = value?.filter((n: string | null): n is string => Boolean(n)) ?? []
                const xColumn: ChartAxis | undefined =
                    values.selectedXAxis !== null ? { column: values.selectedXAxis } : undefined

                props.setQuery({
                    ...props.query,
                    chartSettings: {
                        ...(props.query.chartSettings ?? {}),
                        yAxis: yColumns.map((n) => ({ column: n })),
                        xAxis: xColumn,
                    },
                })
            }
        },
    })),
])
