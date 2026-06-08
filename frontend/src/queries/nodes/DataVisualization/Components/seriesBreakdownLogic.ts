import { actions, afterMount, connect, kea, key, listeners, path, props, selectors } from 'kea'

import { DataColorTheme } from 'lib/colors'
import { dataThemeLogic, getColorFromToken } from 'scenes/dataThemeLogic'

import { AxisSeries, AxisSeriesSettings, SelectedYAxis, dataVisualizationLogic } from '../dataVisualizationLogic'
import type { seriesBreakdownLogicType } from './seriesBreakdownLogicType'

/**
 * Sentinel used to key result customizations for null / undefined breakdown values.
 * Mirrors `BREAKDOWN_NULL_STRING_LABEL` from `scenes/insights/utils` to keep the
 * collision-resistance contract consistent with trends/funnels breakdowns.
 */
export const BREAKDOWN_NULL_KEY = '$$_posthog_breakdown_null_$$'

export const getBreakdownValueKey = (value: unknown): string =>
    value === null || value === undefined ? BREAKDOWN_NULL_KEY : String(value)

export interface AxisBreakdownSeries<T> {
    name: string
    /** Stable key derived from the raw breakdown column value, used for result customization lookups. */
    breakdownValue: string
    data: T[]
    settings?: AxisSeriesSettings
}

export interface BreakdownSeriesData<T> {
    xData: AxisSeries<string>
    seriesData: AxisBreakdownSeries<T>[]
    isUnaggregated?: boolean
    warning?: string
}

/** Most series we'll render for a single breakdown before the chart becomes unreadable. */
export const MAX_BREAKDOWN_SERIES = 50

/** Short label shown when a breakdown is capped — pairs with the detailed warning below. */
export const BREAKDOWN_LIMIT_LABEL = `Breakdowns are limited to ${MAX_BREAKDOWN_SERIES}`

/** Detailed, count-aware copy shown in the cap's info tooltip. */
export const getBreakdownLimitWarning = (totalValues: number): string =>
    `Showing the top ${MAX_BREAKDOWN_SERIES} breakdown values by total out of ${totalValues}. Refine your query to narrow the breakdown.`

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
            dataThemeLogic,
            ['getTheme'],
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
                s.getTheme,
            ],
            (
                selectedBreakdownColumn,
                breakdownColumnValues,
                ySeries,
                xSeries,
                response,
                columns,
                chartSettings,
                getTheme: (themeId: string | number | null | undefined) => DataColorTheme | null
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

                const data: any[] =
                    'results' in response && Array.isArray(response.results)
                        ? response.results
                        : 'result' in response && Array.isArray(response.result)
                          ? response.result
                          : []

                const yColumns = yAxis
                    .map((selectedYAxis) => columns.find((n) => n.name === selectedYAxis.name))
                    .filter((column): column is NonNullable<typeof column> => Boolean(column))

                // When there are more breakdown values than we can legibly chart, keep the
                // most significant ones (highest total across the y-series) rather than an
                // arbitrary first-N, and tell the user we capped it.
                let visibleBreakdownValues = breakdownColumnValues
                let warning: string | undefined
                if (breakdownColumnValues.length > MAX_BREAKDOWN_SERIES) {
                    const totalByValue = new Map<unknown, number>()
                    for (const row of data) {
                        const rowTotal = yColumns.reduce((sum, yColumn) => {
                            const numeric = Number(row[yColumn.dataIndex])
                            return Number.isNaN(numeric) ? sum : sum + numeric
                        }, 0)
                        const breakdownValue = row[breakdownColumn.dataIndex]
                        totalByValue.set(breakdownValue, (totalByValue.get(breakdownValue) ?? 0) + rowTotal)
                    }

                    visibleBreakdownValues = [...breakdownColumnValues]
                        .sort((a, b) => (totalByValue.get(b) ?? 0) - (totalByValue.get(a) ?? 0))
                        .slice(0, MAX_BREAKDOWN_SERIES)
                    warning = getBreakdownLimitWarning(breakdownColumnValues.length)
                }

                // xData is unique x values
                const xData = Array.from(new Set(data.map((n) => n[xColumn.dataIndex])))

                let isUnaggregated = false

                const multipleYSeries = yAxis.length > 1
                const showNullsAsZero = chartSettings.showNullsAsZero ?? false
                const resultCustomizations = chartSettings.resultCustomizations ?? {}
                const theme = getTheme(undefined)

                const seriesData: AxisBreakdownSeries<number | null>[] = yAxis.flatMap((selectedYAxis) => {
                    const yColumn = columns.find((n) => n.name === selectedYAxis.name)
                    if (!yColumn) {
                        return []
                    }

                    return visibleBreakdownValues.map<AxisBreakdownSeries<number | null>>((value) => {
                        const seriesName = multipleYSeries
                            ? `${selectedYAxis.name} - ${value || '[No value]'}`
                            : value || '[No value]'
                        const breakdownValue = getBreakdownValueKey(value)
                        const customColorToken = resultCustomizations[breakdownValue]?.color
                        const customColor =
                            customColorToken && theme ? getColorFromToken(theme, customColorToken) : undefined

                        // first filter data by breakdown column value
                        const filteredData = data.filter((n) => n[breakdownColumn.dataIndex] === value)
                        if (filteredData.length === 0) {
                            return {
                                name: seriesName,
                                breakdownValue,
                                data: [],
                                settings: customColor ? { display: { color: customColor } } : undefined,
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
                            breakdownValue,
                            data: dataset,
                            // we copy supported settings over from the selected
                            // y-axis since we don't support setting these on the
                            // breakdown series at the moment. The per-breakdown
                            // color customization (if any) wins over the inherited
                            // y-axis color.
                            settings: {
                                formatting: selectedYAxis.settings.formatting,
                                display: {
                                    yAxisPosition: selectedYAxis.settings?.display?.yAxisPosition,
                                    displayType: selectedYAxis.settings?.display?.displayType,
                                    color: customColor,
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
                    warning,
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
