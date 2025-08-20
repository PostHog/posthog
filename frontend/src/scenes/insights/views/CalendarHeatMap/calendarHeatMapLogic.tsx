import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'
import { teamLogic } from 'scenes/teamLogic'

import { InsightLogicProps, TrendResult } from '~/types'

import { keyForInsightLogicProps } from '../../sharedUtils'
import type { calendarHeatMapLogicType } from './calendarHeatMapLogicType'
import { DaysAbbreviated, HoursAbbreviated } from './utils'

export interface CalendarHeatMapProcessedData {
    matrix: number[][]
    columnsAggregations: number[]
    rowsAggregations: number[]
    overallValue: number
    maxOverall: number
    minOverall: number
    maxRowAggregation: number
    minRowAggregation: number
    maxColumnAggregation: number
    minColumnAggregation: number
}

export const calendarHeatMapLogic = kea<calendarHeatMapLogicType>([
    props({} as InsightLogicProps),
    key(keyForInsightLogicProps('new')),
    path((key) => ['scenes', 'insights', 'CalendarHeatMap', 'calendarHeatMapLogic', key]),
    connect((props: InsightLogicProps) => ({
        values: [
            insightVizDataLogic(props),
            ['insightData', 'trendsFilter', 'breakdownFilter', 'series', 'querySource', 'theme'],
            teamLogic,
            ['weekStartDay'],
        ],
    })),
    actions({
        showTooltip: (row: number, column: number, value: number) => ({ row, column, value }),
        hideTooltip: true,
        updateTooltipCoordinates: (x: number, y: number) => ({ x, y }),
    }),
    reducers({
        isTooltipShown: [
            false,
            {
                showTooltip: () => true,
                hideTooltip: () => false,
            },
        ],
        currentTooltip: [
            null as [number, number, number] | null,
            {
                showTooltip: (_, { row, column, value }) => [row, column, value],
            },
        ],
        tooltipCoordinates: [
            null as [number, number] | null,
            {
                updateTooltipCoordinates: (_, { x, y }) => [x, y],
            },
        ],
    }),
    selectors({
        processedData: [
            (s) => [s.insightData, s.weekStartDay],
            (insightData, weekStartDay): CalendarHeatMapProcessedData => {
                // Default empty data structure
                const emptyData = {
                    matrix: Array(7)
                        .fill(null)
                        .map(() => Array(24).fill(0)),
                    columnsAggregations: Array(24).fill(0),
                    rowsAggregations: Array(7).fill(0),
                    overallValue: 0,
                    maxOverall: 0,
                    minOverall: 0,
                    maxRowAggregation: 0,
                    minRowAggregation: 0,
                    maxColumnAggregation: 0,
                    minColumnAggregation: 0,
                }

                // Check if we have heatmap data in the trends response
                if (!Array.isArray(insightData?.result) || insightData.result.length === 0) {
                    return emptyData
                }

                const result = insightData.result[0] as TrendResult & {
                    calendar_heatmap_data?: {
                        data: Array<{ row: number; column: number; value: number }>
                        rowAggregations: Array<{ row: number; value: number }>
                        columnAggregations: Array<{ column: number; value: number }>
                        allAggregations: number
                    }
                }

                if (!result.calendar_heatmap_data) {
                    return emptyData
                }

                const { data, rowAggregations, columnAggregations, allAggregations } = result.calendar_heatmap_data

                const matrix: number[][] = []
                let maxOverall = 0
                let minOverall = Infinity

                // Initialize matrix (7 days x 24 hours)
                for (let row = 0; row < 7; row++) {
                    matrix[row] = []
                    for (let column = 0; column < 24; column++) {
                        matrix[row][column] = 0
                    }
                }

                // Fill matrix with data, adjusting for week start day
                if (data && data.length > 0) {
                    data.forEach((result) => {
                        // Ensure we have valid data
                        if (
                            typeof result.row === 'number' &&
                            typeof result.column === 'number' &&
                            typeof result.value === 'number'
                        ) {
                            // Convert ClickHouse toDayOfWeek (1=Mon, 2=Tue, ..., 7=Sun) to standard format (0=Sun, 1=Mon, ...)
                            const standardDay = result.row % 7
                            // Adjust for team's week start day setting
                            const adjustedDay = (standardDay - weekStartDay + 7) % 7
                            // Ensure indices are within bounds
                            if (adjustedDay >= 0 && adjustedDay < 7 && result.column >= 0 && result.column < 24) {
                                matrix[adjustedDay][result.column] = result.value
                                maxOverall = Math.max(maxOverall, result.value)
                                minOverall = Math.min(minOverall, result.value)
                            }
                        }
                    })
                }

                // Handle edge case where there is no data
                if (minOverall === Infinity) {
                    minOverall = 0
                }

                // Calculate columns aggregations
                const columnsAggregations: number[] = Array.from({ length: 24 }, () => 0)
                if (columnAggregations && columnAggregations.length > 0) {
                    columnAggregations.forEach((result) => {
                        if (
                            typeof result.column === 'number' &&
                            typeof result.value === 'number' &&
                            result.column >= 0 &&
                            result.column < 24
                        ) {
                            columnsAggregations[result.column] = result.value
                        }
                    })
                }

                // Calculate rows aggregations, adjusting for week start day
                const rowsAggregations: number[] = Array.from({ length: 7 }, () => 0)
                if (rowAggregations && rowAggregations.length > 0) {
                    rowAggregations.forEach((result) => {
                        if (typeof result.row === 'number' && typeof result.value === 'number') {
                            // Convert ClickHouse toDayOfWeek (1=Mon, 2=Tue, ..., 7=Sun) to standard format (0=Sun, 1=Mon, ...)
                            const standardDay = result.row % 7
                            // Adjust for team's week start day setting
                            const adjustedDay = (standardDay - weekStartDay + 7) % 7
                            if (adjustedDay >= 0 && adjustedDay < 7) {
                                rowsAggregations[adjustedDay] = result.value
                            }
                        }
                    })
                }

                const maxRowAggregation = rowsAggregations.length > 0 ? Math.max(...rowsAggregations) : 0
                const minRowAggregation = rowsAggregations.length > 0 ? Math.min(...rowsAggregations) : 0
                const maxColumnAggregation = columnsAggregations.length > 0 ? Math.max(...columnsAggregations) : 0
                const minColumnAggregation = columnsAggregations.length > 0 ? Math.min(...columnsAggregations) : 0
                const overallValue = allAggregations ?? 0

                return {
                    matrix,
                    columnsAggregations,
                    rowsAggregations,
                    overallValue,
                    maxOverall,
                    minOverall,
                    maxRowAggregation,
                    minRowAggregation,
                    maxColumnAggregation,
                    minColumnAggregation,
                }
            },
        ],
        rowLabels: [
            (s) => [s.weekStartDay],
            (weekStartDay): string[] => {
                return Array.from({ length: DaysAbbreviated.values.length }, (_, i) => {
                    const adjustedDay = (i + weekStartDay) % DaysAbbreviated.values.length
                    return DaysAbbreviated.values[adjustedDay]
                })
            },
        ],
        columnLabels: [() => [], (): string[] => HoursAbbreviated.values],
    }),
])
