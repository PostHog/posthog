import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'

import { AxisSeries, AxisSeriesSettings, SelectedYAxis, dataVisualizationLogic } from '../dataVisualizationLogic'
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

export const EmptyBreakdownSeries: BreakdownSeriesData<number | null> = {
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

const createEmptyBreakdownSeriesWithError = (error: string): BreakdownSeriesData<number | null> => {
    return {
        ...EmptyBreakdownSeries,
        error,
    }
}

const parseBreakdownSeriesValue = (value: unknown, selectedYAxis: SelectedYAxis): number | null => {
    if (value === undefined || value === null || Number.isNaN(value)) {
        return null
    }

    try {
        const multiplier = selectedYAxis.settings.formatting?.style === 'percent' ? 100 : 1

        if (selectedYAxis.settings.formatting?.decimalPlaces) {
            const parsed = parseFloat(
                (parseFloat(String(value)) * multiplier).toFixed(selectedYAxis.settings.formatting.decimalPlaces)
            )
            return Number.isNaN(parsed) ? null : parsed
        }

        const parsed = Number.isInteger(value)
            ? parseInt(String(value), 10) * multiplier
            : parseFloat(String(value)) * multiplier
        return Number.isNaN(parsed) ? null : parsed
    } catch {
        return null
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
        values: [
            dataVisualizationLogic,
            ['query', 'response', 'columns', 'selectedXAxis', 'selectedYAxis', 'chartSettings'],
        ],
    })),
    actions(({ values }) => ({
        addSeriesBreakdown: (columnName: string | null) => ({ columnName, response: values.response }),
        deleteSeriesBreakdown: () => ({}),
    })),
    selectors({
        selectedSeriesBreakdownColumn: [
            (s) => [s.query],
            (query): string | null | undefined => {
                return query?.chartSettings?.seriesBreakdownColumn
            },
        ],
        showSeriesBreakdown: [
            (s) => [s.selectedSeriesBreakdownColumn],
            (selectedSeriesBreakdownColumn): boolean => selectedSeriesBreakdownColumn !== undefined,
        ],
        breakdownColumnValues: [
            (s) => [s.selectedSeriesBreakdownColumn, s.response, s.columns],
            (breakdownColumn, response, columns): string[] => {
                if (!response || breakdownColumn === null) {
                    return []
                }

                const data = 'results' in response ? response.results : 'result' in response ? response.result : []

                const column = columns.find((n) => n.name === breakdownColumn)
                if (!column) {
                    return []
                }

                // return list of unique column values
                return Array.from(new Set(data.map((n: any) => n[column.dataIndex])))
            },
        ],
        seriesBreakdownData: [
            (s) => [
                s.selectedSeriesBreakdownColumn,
                s.breakdownColumnValues,
                s.selectedYAxis,
                s.selectedXAxis,
                s.response,
                s.columns,
                s.chartSettings,
            ],
            (
                selectedBreakdownColumn,
                breakdownColumnValues,
                ySeries,
                xSeries,
                response,
                columns,
                chartSettings
            ): BreakdownSeriesData<number | null> => {
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

                const yAxis = ySeries.filter((n): n is SelectedYAxis => Boolean(n))
                if (!yAxis || !yAxis.length) {
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

                const data: any[] =
                    'results' in response && Array.isArray(response.results)
                        ? response.results
                        : 'result' in response && Array.isArray(response.result)
                          ? response.result
                          : []

                // xData is unique x values
                const xData = Array.from(new Set(data.map((n) => n[xColumn.dataIndex])))

                let isUnaggregated = false

                const multipleYSeries = yAxis.length > 1
                const showNullsAsZero = chartSettings.showNullsAsZero ?? false

                const seriesData: AxisBreakdownSeries<number | null>[] = yAxis.flatMap((selectedYAxis) => {
                    const yColumn = columns.find((n) => n.name === selectedYAxis.name)
                    if (!yColumn) {
                        return []
                    }

                    return breakdownColumnValues.map<AxisBreakdownSeries<number | null>>((value) => {
                        const seriesName = multipleYSeries
                            ? `${selectedYAxis.name} - ${value || '[No value]'}`
                            : value || '[No value]'

                        // first filter data by breakdown column value
                        const filteredData = data.filter((n) => n[breakdownColumn.dataIndex] === value)
                        if (filteredData.length === 0) {
                            return {
                                name: seriesName,
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

                        // Missing buckets should remain null unless the chart explicitly
                        // requests zero-filling, matching the non-breakdown series path.
                        const dataset = xData.map((xValue) => {
                            const numericValues = filteredData
                                .filter((n) => n[xColumn.dataIndex] === xValue)
                                .map((n) => parseBreakdownSeriesValue(n[yColumn.dataIndex], selectedYAxis))
                                .filter((value): value is number => value !== null)

                            if (numericValues.length === 0) {
                                return showNullsAsZero ? 0 : null
                            }

                            return numericValues.reduce((a, b) => a + b, 0)
                        })

                        return {
                            name: seriesName,
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
    listeners(({ actions }) => ({
        addSeriesBreakdown: ({ columnName }) => {
            actions.setQuery((query) => ({
                ...query,
                chartSettings: {
                    ...query.chartSettings,
                    seriesBreakdownColumn: columnName,
                },
            }))
        },
        deleteSeriesBreakdown: () => {
            actions.setQuery((query) => {
                return {
                    ...query,
                    chartSettings: {
                        ...query.chartSettings,
                        seriesBreakdownColumn: undefined,
                    },
                }
            })
        },
        clearAxis: () => {
            actions.setQuery((query) => ({
                ...query,
                chartSettings: {
                    ...query.chartSettings,
                    seriesBreakdownColumn: undefined,
                },
            }))
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.query.chartSettings?.seriesBreakdownColumn === undefined) {
            actions.deleteSeriesBreakdown()
        }
    }),
])
