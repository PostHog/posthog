import './EventsHeatMap.scss'

import { useValues } from 'kea'
import { humanFriendlyNumber } from 'lib/utils'
import React, { useCallback, useEffect, useState } from 'react'
import { dataThemeLogic } from 'scenes/dataThemeLogic'
import { InsightLoadingState } from 'scenes/insights/EmptyStates'
import { InsightsWrapper } from 'scenes/insights/InsightsWrapper'
import { teamLogic } from 'scenes/teamLogic'

import { useResizeObserver } from '~/lib/hooks/useResizeObserver'
import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import {
    AnyResponseType,
    WebActiveHoursHeatMapDayAndHourResult,
    WebActiveHoursHeatMapDayResult,
    WebActiveHoursHeatMapHourResult,
    WebActiveHoursHeatMapQuery,
    WebActiveHoursHeatMapStructuredResult,
} from '~/queries/schema/schema-general'
import { QueryContext } from '~/queries/types'

import { AggregationLabel, AxisConfig, DaysAbbreviated, HoursAbbreviated } from './config'
import { HeatMapCell, HeatMapValues } from './HeatMapCell'
interface EventsHeatMapProps {
    query: WebActiveHoursHeatMapQuery
    context: QueryContext
    cachedResults?: AnyResponseType
}

export function EventsHeatMap({ query, context, cachedResults }: EventsHeatMapProps): JSX.Element {
    const { themes, getTheme } = useValues(dataThemeLogic)
    const { weekStartDay } = useValues(teamLogic)
    const theme = getTheme(themes?.[0]?.id)
    const { ref: elementRef, width } = useResizeObserver()

    const heatmapColor = theme?.['preset-1'] ?? '#000000' // Default to black if no color found
    const aggregationColor = theme?.['preset-2'] ?? '#000000' // Default to black if no color found
    const backgroundColorOverall = theme?.['preset-3'] ?? '#000000' // Default to black if no color found
    const [fontSize, setFontSize] = useState(13)

    const updateSize = useCallback(() => {
        if (!elementRef || !width) {
            return
        }

        // These numbers are thresholds for the table's width, if we do not update the fontSize, the table overflows horizontally
        if (width < 1007) {
            // If the width is less than 1007, we virtually hide the text and show the tooltip on hover
            setFontSize(0)
        } else if (width < 1134) {
            setFontSize(9)
        } else if (width < 1160) {
            setFontSize(11)
        } else {
            setFontSize(11.5)
        }
    }, [elementRef, width])

    useEffect(() => {
        const element = elementRef
        if (!element) {
            return
        }

        updateSize()
    }, [elementRef, updateSize])

    const { response, responseLoading, queryId } = useValues(
        dataNodeLogic({
            query,
            key: 'events-heat-map',
            dataNodeCollectionId: context.insightProps?.dataNodeCollectionId,
            cachedResults,
        })
    )

    if (responseLoading) {
        return (
            <InsightsWrapper>
                <InsightLoadingState queryId={queryId} key={queryId} insightProps={context.insightProps ?? {}} />
            </InsightsWrapper>
        )
    }

    const {
        matrix,
        maxOverall,
        minOverall,
        rowsAggregations,
        columnsAggregations,
        maxRowAggregation,
        minRowAggregation,
        maxColumnAggregation,
        minColumnAggregation,
        overallValue,
    } = processData(weekStartDay, response?.results ?? [])

    const rotatedYLabels = Array.from({ length: DaysAbbreviated.values.length }, (_, i) => {
        const adjustedDay = (i + weekStartDay) % DaysAbbreviated.values.length
        return DaysAbbreviated.values[adjustedDay]
    })

    return (
        <div className="EventsHeatMapContainer" ref={elementRef}>
            <table
                className="EventsHeatMap"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ '--heatmap-table-color': heatmapColor } as React.CSSProperties}
            >
                <tbody>
                    {/* Header row */}
                    <tr>
                        <th className="bg" />
                        {HoursAbbreviated.values.map((label, i) => (
                            <th key={i}>{label}</th>
                        ))}
                        {columnsAggregations[0] !== undefined && (
                            <th className="aggregation-border">{AggregationLabel.All}</th>
                        )}
                    </tr>

                    {/* Data rows */}
                    {rotatedYLabels.map((day, yIndex) => (
                        <tr key={yIndex}>
                            <td className="EventsHeatMap__TextTab">{day}</td>
                            {renderDataCells(
                                HoursAbbreviated,
                                matrix[yIndex],
                                maxOverall,
                                minOverall,
                                day,
                                fontSize,
                                heatmapColor
                            )}
                            {renderColumnsAggregationCell(
                                {
                                    value: columnsAggregations[yIndex],
                                    maxValue: maxColumnAggregation,
                                    minValue: minColumnAggregation,
                                },
                                day,
                                fontSize,
                                aggregationColor
                            )}
                        </tr>
                    ))}

                    {/* Aggregation row */}
                    <tr className="aggregation-border">
                        {rowsAggregations[0] !== undefined && (
                            <td className="EventsHeatMap__TextTab">{AggregationLabel.All}</td>
                        )}
                        {renderRowAggregationCells(
                            rowsAggregations,
                            HoursAbbreviated,
                            maxRowAggregation,
                            minRowAggregation,
                            fontSize,
                            aggregationColor
                        )}
                        {renderOverallCell(overallValue, fontSize, backgroundColorOverall)}
                    </tr>
                </tbody>
            </table>
        </div>
    )
}

function processData(
    weekStartDay: number,
    results?: WebActiveHoursHeatMapStructuredResult
): {
    matrix: { [key: number]: { [key: number]: number } }
    maxOverall: number
    minOverall: number
    rowsAggregations: { [key: number]: number }
    columnsAggregations: { [key: number]: number }
    maxRowAggregation: number
    minRowAggregation: number
    maxColumnAggregation: number
    minColumnAggregation: number
    overallValue: number
} {
    const matrix: { [key: number]: { [key: number]: number } } = {}
    let maxOverall = 0
    let minOverall = Infinity

    // Initialize matrix
    for (let row = 0; row < DaysAbbreviated.values.length; row++) {
        matrix[row] = {}
        for (let column = 0; column < HoursAbbreviated.values.length; column++) {
            matrix[row][column] = 0
        }
    }

    // Fill matrix with day-hour combinations
    if (results?.dayAndHours) {
        results.dayAndHours.forEach((result: WebActiveHoursHeatMapDayAndHourResult) => {
            const adjustedDay = (result.day - weekStartDay) % DaysAbbreviated.values.length
            matrix[adjustedDay][result.hour] = result.total
            maxOverall = Math.max(maxOverall, result.total)
            minOverall = Math.min(minOverall, result.total)
        })
    }

    // Calculate x aggregations from hours data
    const rowsAggregations: { [key: number]: number } = Array.from({ length: HoursAbbreviated.values.length }, () => 0)
    if (results?.hours) {
        results.hours.forEach((result: WebActiveHoursHeatMapHourResult) => {
            rowsAggregations[result.hour] = result.total
        })
    }

    // Calculate y aggregations from days data
    const columnsAggregations: { [key: number]: number } = Array.from(
        { length: DaysAbbreviated.values.length },
        () => 0
    )
    if (results?.days) {
        results.days.forEach((result: WebActiveHoursHeatMapDayResult) => {
            const adjustedDay = (result.day - weekStartDay) % DaysAbbreviated.values.length
            columnsAggregations[adjustedDay] = result.total
        })
    }

    const maxRowAggregation = Math.max(...Object.values(rowsAggregations), 0)
    const minRowAggregation = Math.min(...Object.values(rowsAggregations), Infinity)
    const maxColumnAggregation = Math.max(...Object.values(columnsAggregations), 0)
    const minColumnAggregation = Math.min(...Object.values(columnsAggregations), Infinity)
    const overallValue = results?.total ?? 0

    return {
        matrix,
        maxOverall,
        minOverall,
        rowsAggregations,
        columnsAggregations,
        maxRowAggregation,
        minRowAggregation,
        maxColumnAggregation,
        minColumnAggregation,
        overallValue,
    }
}

function renderOverallCell(overallValue: number, fontSize: number, bg: string): JSX.Element {
    return (
        <td className="aggregation-border">
            <HeatMapCell
                fontSize={fontSize}
                values={{
                    value: overallValue,
                    maxValue: overallValue,
                    minValue: 0,
                }}
                bg={bg}
                tooltip={`${AggregationLabel.All} - ${humanFriendlyNumber(overallValue)}`}
            />
        </td>
    )
}

function renderRowAggregationCells(
    rowsAggregations: { [key: number]: number },
    columns: AxisConfig,
    maxRowAggregation: number,
    minRowAggregation: number,
    fontSize: number,
    bg: string
): JSX.Element[] {
    return columns.values.map((hour, index) => (
        <td key={index}>
            <HeatMapCell
                fontSize={fontSize}
                values={{
                    value: rowsAggregations[index],
                    maxValue: maxRowAggregation,
                    minValue: minRowAggregation,
                }}
                bg={bg}
                tooltip={`${AggregationLabel.All} - ${String(hour).padStart(2, '0')}:00 - ${humanFriendlyNumber(
                    rowsAggregations[index]
                )}`}
            />
        </td>
    ))
}

function renderColumnsAggregationCell(values: HeatMapValues, day: string, fontSize: number, bg: string): JSX.Element {
    return (
        <td className="aggregation-border">
            <HeatMapCell
                fontSize={fontSize}
                values={values}
                bg={bg}
                tooltip={`${AggregationLabel.All} - ${day} - ${humanFriendlyNumber(values.value)}`}
            />
        </td>
    )
}

function renderDataCells(
    columns: AxisConfig,
    rowData: { [key: number]: number },
    maxValue: number,
    minValue: number,
    day: string,
    fontSize: number,
    bg: string
): JSX.Element[] {
    return columns.values.map((hour, index) => (
        <td key={index}>
            <HeatMapCell
                fontSize={fontSize}
                values={{
                    value: rowData[index],
                    maxValue,
                    minValue,
                }}
                bg={bg}
                tooltip={`${day} - ${String(hour).padStart(2, '0')}:00 - ${humanFriendlyNumber(rowData[index])}`}
            />
        </td>
    ))
}
