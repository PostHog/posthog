import './EventsHeatMap.scss'

import { useValues } from 'kea'
import React, { useCallback, useEffect, useState } from 'react'
import { dataThemeLogic } from 'scenes/dataThemeLogic'

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

import { AggregationLabel, DaysAbbreviated, HoursAbbreviated } from './config'
import { HeatMapCell } from './HeatMapCell'

interface EventsHeatMapProps {
    query: WebActiveHoursHeatMapQuery
    context: QueryContext
    cachedResults?: AnyResponseType
}

export function EventsHeatMap({ query, context, cachedResults }: EventsHeatMapProps): JSX.Element {
    const { themes, getTheme } = useValues(dataThemeLogic)
    const theme = getTheme(themes?.[0]?.id)
    const { ref: elementRef, width } = useResizeObserver()

    const heatmapColor = theme?.['preset-1'] ?? '#000000' // Default to black if no color found
    const aggregationColor = theme?.['preset-2'] ?? '#000000' // Default to black if no color found
    const backgroundColorOverall = theme?.['preset-3'] ?? '#000000' // Default to black if no color found
    const [fontSize, setFontSize] = useState(13)
    const [showTooltip, setShowTooltip] = useState(false)

    const updateSize = useCallback(() => {
        if (!elementRef || !width) {
            return
        }

        // These numbers are thresholds for the table's width, if we do not update the fontSize, the table overflows horizontally
        if (width < 1007) {
            // If the width is less than 1007, we virtually hide the text and show the tooltip on hover
            setFontSize(0)
            setShowTooltip(true)
        } else if (width < 1134) {
            setFontSize(9)
            setShowTooltip(false)
        } else if (width < 1160) {
            setFontSize(11)
            setShowTooltip(false)
        } else {
            setFontSize(11.5)
            setShowTooltip(false)
        }
    }, [elementRef, width])

    useEffect(() => {
        const element = elementRef
        if (!element) {
            return
        }

        updateSize()
    }, [elementRef, updateSize])

    const { response } = useValues(
        dataNodeLogic({
            query,
            key: 'events-heat-map',
            dataNodeCollectionId: context.insightProps?.dataNodeCollectionId,
            cachedResults,
        })
    )

    const { matrix, maxOverall, xAggregations, yAggregations, maxXAggregation, maxYAggregation, overallValue } =
        processData(response?.results ?? [])

    const rotatedYLabels = [
        ...DaysAbbreviated.values.slice(DaysAbbreviated.startIndex || 0),
        ...DaysAbbreviated.values.slice(0, DaysAbbreviated.startIndex || 0),
    ]

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
                        {yAggregations[0] !== undefined && (
                            <th className="aggregation-border">{AggregationLabel.All}</th>
                        )}
                    </tr>

                    {/* Data rows */}
                    {rotatedYLabels.map((day, yIndex) => (
                        <tr key={yIndex}>
                            <td className="EventsHeatMap__TextTab">{day}</td>
                            {renderDataCells(matrix[yIndex], maxOverall, day, showTooltip, fontSize, heatmapColor)}
                            {renderYAggregationCell(
                                yAggregations[yIndex],
                                maxYAggregation,
                                day,
                                showTooltip,
                                fontSize,
                                aggregationColor
                            )}
                        </tr>
                    ))}

                    {/* Aggregation row */}
                    <tr className="aggregation-border">
                        {xAggregations[0] !== undefined && (
                            <td className="EventsHeatMap__TextTab">{AggregationLabel.All}</td>
                        )}
                        {renderAggregationCells(
                            xAggregations,
                            maxXAggregation,
                            showTooltip,
                            fontSize,
                            aggregationColor
                        )}
                        {renderOverallCell(overallValue, showTooltip, fontSize, backgroundColorOverall)}
                    </tr>
                </tbody>
            </table>
        </div>
    )
}

function processData(results?: WebActiveHoursHeatMapStructuredResult): {
    matrix: { [key: number]: { [key: number]: number } }
    maxOverall: number
    xAggregations: { [key: number]: number }
    yAggregations: { [key: number]: number }
    maxXAggregation: number
    maxYAggregation: number
    overallValue: number
} {
    const matrix: { [key: number]: { [key: number]: number } } = {}
    let maxOverall = 0

    // Initialize matrix
    for (let i = 0; i < DaysAbbreviated.values.length; i++) {
        matrix[i] = {}
        for (let x = 0; x < HoursAbbreviated.values.length; x++) {
            matrix[i][x] = 0
        }
    }

    // Fill matrix with day-hour combinations
    if (results?.dayAndHours) {
        results.dayAndHours.forEach((result: WebActiveHoursHeatMapDayAndHourResult) => {
            const adjustedDay =
                (result.day - (DaysAbbreviated.startIndex || 0) + DaysAbbreviated.values.length) %
                DaysAbbreviated.values.length
            matrix[adjustedDay][result.hour] = result.total
            maxOverall = Math.max(maxOverall, result.total)
        })
    }

    // Calculate x aggregations from hours data
    const xAggregations: { [key: number]: number } = Array.from({ length: HoursAbbreviated.values.length }, () => 0)
    if (results?.hours) {
        results.hours.forEach((result: WebActiveHoursHeatMapHourResult) => {
            xAggregations[result.hour] = result.total
        })
    }

    // Calculate y aggregations from days data
    const yAggregations: { [key: number]: number } = Array.from({ length: DaysAbbreviated.values.length }, () => 0)
    if (results?.days) {
        results.days.forEach((result: WebActiveHoursHeatMapDayResult) => {
            const adjustedDay =
                (result.day - (DaysAbbreviated.startIndex || 0) + DaysAbbreviated.values.length) %
                DaysAbbreviated.values.length
            yAggregations[adjustedDay] = result.total
        })
    }

    const maxXAggregation = Math.max(...Object.values(xAggregations), 0)
    const maxYAggregation = Math.max(...Object.values(yAggregations), 0)
    const overallValue = results?.total ?? 0

    return {
        matrix,
        maxOverall,
        xAggregations,
        yAggregations,
        maxXAggregation,
        maxYAggregation,
        overallValue,
    }
}

function renderOverallCell(
    overallValue: number,
    showTooltip: boolean,
    fontSize: number,
    backgroundColorOverall: string
): JSX.Element {
    return (
        <td className="aggregation-border">
            <HeatMapCell
                showTooltip={showTooltip}
                fontSize={fontSize}
                value={overallValue}
                maxValue={overallValue}
                backgroundColor={backgroundColorOverall}
                dayAndTime={AggregationLabel.All}
            />
        </td>
    )
}

function renderAggregationCells(
    xAggregations: { [key: number]: number },
    maxXAggregation: number,
    showTooltip: boolean,
    fontSize: number,
    aggregationColor: string
): JSX.Element[] {
    return Array.from({ length: HoursAbbreviated.values.length }, (_, x) => (
        <td key={x}>
            <HeatMapCell
                showTooltip={showTooltip}
                fontSize={fontSize}
                value={xAggregations[x]}
                maxValue={maxXAggregation}
                backgroundColor={aggregationColor}
                dayAndTime={`${AggregationLabel.All} - ${String(x).padStart(2, '0')}:00`}
            />
        </td>
    ))
}

function renderYAggregationCell(
    value: number,
    maxYAggregation: number,
    day: string,
    showTooltip: boolean,
    fontSize: number,
    aggregationColor: string
): JSX.Element {
    return (
        <td className="aggregation-border">
            <HeatMapCell
                showTooltip={showTooltip}
                fontSize={fontSize}
                value={value}
                maxValue={maxYAggregation}
                backgroundColor={aggregationColor}
                dayAndTime={`${AggregationLabel.All} - ${day}`}
            />
        </td>
    )
}

function renderDataCells(
    rowData: { [key: number]: number },
    maxValue: number,
    day: string,
    showTooltip: boolean,
    fontSize: number,
    heatmapColor: string
): JSX.Element[] {
    return Array.from({ length: HoursAbbreviated.values.length }, (_, x) => (
        <td key={x}>
            <HeatMapCell
                showTooltip={showTooltip}
                fontSize={fontSize}
                value={rowData[x]}
                maxValue={maxValue}
                backgroundColor={heatmapColor}
                dayAndTime={`${day} - ${String(x).padStart(2, '0')}:00`}
            />
        </td>
    ))
}
