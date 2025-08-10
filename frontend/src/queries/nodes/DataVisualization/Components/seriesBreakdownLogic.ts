import { actions, afterMount, connect, kea, key, path, props, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { AxisSeries, AxisSeriesSettings, dataVisualizationLogic } from '../dataVisualizationLogic'
import type { seriesBreakdownLogicType } from './seriesBreakdownLogicType'

export interface AxisBreakdownSeries<T> {
    name: string
    data: T[]
    settings?: AxisSeriesSettings
}

export interface BreakdownSeriesData<T> {
    xData: AxisSeries<string>
    seriesData: AxisBreakdownSeries<T>[]
    isUnaggregated?: boolean
    error?: string
}

export const EmptyBreakdownSeries: BreakdownSeriesData<number> = {
    xData: {
        column: {
            name: 'None',
            type: {
                name: 'INTEGER',
                isNumerical: false,
            },
            label: 'None',
            dataIndex: -1,
        },
        data: [],
    },
    seriesData: [],
}

const createEmptyBreakdownSeriesWithError = (error: string): BreakdownSeriesData<number> => {
    return {
        ...EmptyBreakdownSeries,
        error,
    }
}

export interface SeriesBreakdownLogicProps {
    key: string
}

export const seriesBreakdownLogic = kea<seriesBreakdownLogicType>([
    path(['queries', 'nodes', 'DataVisualization', 'Components', 'seriesBreakdownLogic']),
    key((props) => props.key),
    props({ key: '' } as SeriesBreakdownLogicProps),
    connect(() => ({
        actions: [dataVisualizationLogic, ['clearAxis', 'setQuery']],
        values: [dataVisualizationLogic, ['query', 'response', 'columns', 'selectedXAxis', 'selectedYAxis']],
    })),
    actions(({ values }) => ({
        addSeriesBreakdown: (columnName: string | null) => ({ columnName, response: values.response }),
        deleteSeriesBreakdown: () => ({}),
    })),
    reducers(({ values }) => ({
        showSeriesBreakdown: [
            false as boolean,
            {
                clearAxis: () => false,
                addSeriesBreakdown: () => true,
                deleteSeriesBreakdown: () => false,
            },
        ],
        selectedSeriesBreakdownColumn: [
            values.query?.chartSettings?.seriesBreakdownColumn ?? (null as string | null),
            {
                clearAxis: () => null,
                addSeriesBreakdown: (_, { columnName }) => columnName,
                deleteSeriesBreakdown: () => null,
            },
        ],
    })),
    selectors({
        breakdownColumnValues: [
            (state) => [state.selectedSeriesBreakdownColumn, state.response, state.columns],
            (breakdownColumn, response, columns): string[] => {
                if (!response || breakdownColumn === null) {
                    return []
                }

                const data: any[] = response?.['results'] ?? response?.['result'] ?? []

                const column = columns.find((n) => n.name === breakdownColumn)
                if (!column) {
                    return []
                }

                // return list of unique column values
                return Array.from(new Set(data.map((n) => n[column.dataIndex])))
            },
        ],
        seriesBreakdownData: [
            (state) => [
                state.selectedSeriesBreakdownColumn,
                state.breakdownColumnValues,
                state.selectedYAxis,
                state.selectedXAxis,
                state.response,
                state.columns,
            ],
            (
                selectedBreakdownColumn,
                breakdownColumnValues,
                ySeries,
                xSeries,
                response,
                columns
            ): BreakdownSeriesData<number> => {
                if (
                    !response ||
                    !selectedBreakdownColumn ||
                    ySeries === null ||
                    ySeries.length === 0 ||
                    xSeries === null ||
                    columns === null ||
                    columns.length === 0
                ) {
                    return EmptyBreakdownSeries
                }

                // shouldn't be possible to have more than 1 ySeries with a breakdown
                if (ySeries.length > 1) {
                    return EmptyBreakdownSeries
                }

                const selectedYAxis = ySeries[0]
                if (!selectedYAxis) {
                    return EmptyBreakdownSeries
                }
                const yColumn = columns.find((n) => n.name === selectedYAxis.name)
                if (!yColumn) {
                    return EmptyBreakdownSeries
                }
                const xColumn = columns.find((n) => n.name === xSeries)
                if (!xColumn) {
                    return EmptyBreakdownSeries
                }

                const breakdownColumn = columns.find((n) => n.name === selectedBreakdownColumn)
                if (!breakdownColumn) {
                    return EmptyBreakdownSeries
                }

                if (breakdownColumnValues.length > 50) {
                    return createEmptyBreakdownSeriesWithError('Too many breakdown values (max 50)')
                }

                const data: any[] = response?.['results'] ?? response?.['result'] ?? []

                // xData is unique x values
                const xData = Array.from(new Set(data.map((n) => n[xColumn.dataIndex])))

                let isUnaggregated = false

                const seriesData: AxisBreakdownSeries<number>[] = breakdownColumnValues.map((value) => {
                    // first filter data by breakdown column value
                    const filteredData = data.filter((n) => n[breakdownColumn.dataIndex] === value)
                    if (filteredData.length === 0) {
                        return {
                            name: value,
                            data: [],
                        }
                    }

                    // check if there are any duplicates of xColumn values
                    // (if we know there is unaggregated data, we don't need to check again)
                    if (!isUnaggregated) {
                        const xColumnValues = filteredData.map((n) => n[xColumn.dataIndex])
                        const xColumnValuesSet = new Set(xColumnValues)
                        if (xColumnValues.length !== xColumnValuesSet.size) {
                            isUnaggregated = true
                        }
                    }

                    // sum y values for each x value, setting to 0 if no corresponding y value
                    const dataset = xData.map((xValue) => {
                        const yValue = filteredData
                            .filter((n) => n[xColumn.dataIndex] === xValue)
                            .map((n) => {
                                try {
                                    const value = n[yColumn.dataIndex]
                                    const multiplier = selectedYAxis.settings.formatting?.style === 'percent' ? 100 : 1

                                    if (selectedYAxis.settings.formatting?.decimalPlaces) {
                                        return parseFloat(
                                            (parseFloat(value) * multiplier).toFixed(
                                                selectedYAxis.settings.formatting.decimalPlaces
                                            )
                                        )
                                    }

                                    const isInt = Number.isInteger(value)
                                    return isInt ? parseInt(value) * multiplier : parseFloat(value) * multiplier
                                } catch {
                                    return 0
                                }
                            })
                            .reduce((a, b) => a + b, 0)
                        return yValue
                    })

                    return {
                        name: value || '[No value]',
                        data: dataset,
                        // we copy supported settings over from the selected
                        // y-axis since we don't support setting these on the
                        // breakdown series at the moment
                        settings: {
                            formatting: selectedYAxis.settings.formatting,
                            display: {
                                yAxisPosition: selectedYAxis.settings?.display?.yAxisPosition,
                                displayType: selectedYAxis.settings?.display?.displayType,
                            },
                        },
                    }
                })

                return {
                    xData: {
                        column: xColumn,
                        data: xData,
                    },
                    seriesData,
                    isUnaggregated,
                }
            },
        ],
    }),
    subscriptions(({ values, actions }) => ({
        selectedSeriesBreakdownColumn: (value: string | null) => {
            actions.setQuery({
                ...values.query,
                chartSettings: {
                    ...values.query.chartSettings,
                    seriesBreakdownColumn: value,
                },
            })
        },
    })),
    afterMount(({ values, actions }) => {
        if (values.query?.chartSettings?.seriesBreakdownColumn) {
            actions.addSeriesBreakdown(values.query.chartSettings.seriesBreakdownColumn)
        }
    }),
])
