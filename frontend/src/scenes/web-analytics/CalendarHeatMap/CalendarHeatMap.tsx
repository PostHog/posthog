import './CalendarHeatMap.scss'

import { LemonSkeleton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import React, { useCallback, useEffect, useState } from 'react'
import { dataThemeLogic } from 'scenes/dataThemeLogic'

import { useResizeObserver } from '~/lib/hooks/useResizeObserver'

import { CalendarHeatMapCell, HeatMapValues } from './CalendarHeatMapCell'

export interface CalendarHeatMapProps {
    isLoading: boolean
    rowLabels: string[]
    columnLabels: string[]
    allAggregationsLabel: string
    backgroundColorsOverride?: {
        allAggregation: string
        rowAggregation: string
        columnAggregation: string
        data: string
    }
    initialFontSize?: number
    thresholdFontSize?: (width: number) => number
    processedData: ProcessedData
    getDataTooltip: (rowLabel: string, columnLabel: string, value: number) => string
    getColumnAggregationTooltip: (columnAggregationLabel: string, columnLabel: string, value: number) => string
    getRowAggregationTooltip: (rowAggregationLabel: string, rowLabel: string, value: number) => string
    getOverallAggregationTooltip: (overallAggregationLabel: string, value: number) => string
}

interface ProcessedData {
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

export function CalendarHeatMap({
    backgroundColorsOverride,
    initialFontSize,
    thresholdFontSize,
    rowLabels,
    columnLabels,
    allAggregationsLabel,
    isLoading,
    processedData,
    getDataTooltip,
    getColumnAggregationTooltip,
    getRowAggregationTooltip,
    getOverallAggregationTooltip,
}: CalendarHeatMapProps): JSX.Element {
    const { themes, getTheme } = useValues(dataThemeLogic)
    const theme = getTheme(themes?.[0]?.id)
    const { ref: elementRef, width } = useResizeObserver()

    const heatmapColor = backgroundColorsOverride?.data ?? theme?.['preset-1'] ?? '#000000' // Default to black if no color found
    const rowAggregationColor = backgroundColorsOverride?.rowAggregation ?? theme?.['preset-2'] ?? '#000000' // Default to black if no color found
    const columnAggregationColor = backgroundColorsOverride?.columnAggregation ?? theme?.['preset-2'] ?? '#000000' // Default to black if no color found
    const backgroundColorOverall = backgroundColorsOverride?.allAggregation ?? theme?.['preset-3'] ?? '#000000' // Default to black if no color found
    const [fontSize, setFontSize] = useState(initialFontSize ?? 13)

    const updateSize = useCallback(() => {
        if (!elementRef || !width) {
            return
        }

        if (thresholdFontSize) {
            setFontSize(thresholdFontSize(width))
        }
    }, [elementRef, width, thresholdFontSize])

    useEffect(() => {
        const element = elementRef
        if (!element) {
            return
        }

        updateSize()
    }, [elementRef, updateSize])

    const {
        matrix,
        maxOverall,
        minOverall,
        columnsAggregations,
        rowsAggregations,
        maxRowAggregation,
        minRowAggregation,
        maxColumnAggregation,
        minColumnAggregation,
        overallValue,
    } = processedData

    return (
        <div className="CalendarHeatMapContainer" ref={elementRef}>
            <table
                className="CalendarHeatMap"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ '--heatmap-table-color': heatmapColor } as React.CSSProperties}
                data-attr="calendar-heatmap"
            >
                {isLoading ? (
                    <LoadingRow />
                ) : (
                    <thead>
                        <tr>
                            <th className="bg" />
                            {columnLabels.map((label, i) => (
                                <th key={i}>{label}</th>
                            ))}
                            {rowsAggregations[0] !== undefined && (
                                <th className="aggregation-border">{allAggregationsLabel}</th>
                            )}
                        </tr>
                    </thead>
                )}
                {isLoading ? (
                    <LoadingRow />
                ) : (
                    <tbody>
                        {/* Data rows */}
                        {rowLabels.map((rowLabel, yIndex) => (
                            <tr key={yIndex}>
                                <td className="CalendarHeatMap__TextTab">{rowLabel}</td>
                                {renderDataCells(
                                    columnLabels,
                                    matrix[yIndex],
                                    maxOverall,
                                    minOverall,
                                    rowLabel,
                                    fontSize,
                                    heatmapColor,
                                    getDataTooltip
                                )}
                                {renderRowsAggregationCell(
                                    {
                                        value: rowsAggregations[yIndex],
                                        maxValue: maxRowAggregation,
                                        minValue: minRowAggregation,
                                    },
                                    rowLabel,
                                    fontSize,
                                    rowAggregationColor,
                                    allAggregationsLabel,
                                    getRowAggregationTooltip
                                )}
                            </tr>
                        ))}

                        {/* Aggregation column */}
                        <tr className="aggregation-border">
                            {columnsAggregations[0] !== undefined && (
                                <td className="CalendarHeatMap__TextTab">{allAggregationsLabel}</td>
                            )}
                            {renderColumnsAggregationCells(
                                columnsAggregations,
                                columnLabels,
                                maxColumnAggregation,
                                minColumnAggregation,
                                fontSize,
                                columnAggregationColor,
                                allAggregationsLabel,
                                getColumnAggregationTooltip
                            )}
                            {renderOverallCell(
                                overallValue,
                                fontSize,
                                backgroundColorOverall,
                                allAggregationsLabel,
                                getOverallAggregationTooltip
                            )}
                        </tr>
                    </tbody>
                )}
            </table>
        </div>
    )
}

function LoadingRow({ cellCount = 14 }: { cellCount?: number }): JSX.Element {
    return (
        <div className="flex items-center justify-center min-h-8 p-0.5 m-0.5">
            <div className="flex gap-1">
                {Array(cellCount)
                    .fill(0)
                    .map((_, i) => (
                        <LemonSkeleton key={i} className="h-8 w-8 rounded" />
                    ))}
            </div>
        </div>
    )
}

function renderOverallCell(
    overallValue: number,
    fontSize: number,
    bg: string,
    allAggregationsLabel: string,
    getOverallAggregationTooltip: (overallAggregationLabel: string, value: number) => string
): JSX.Element {
    return (
        <td className="aggregation-border">
            <CalendarHeatMapCell
                fontSize={fontSize}
                values={{
                    value: overallValue,
                    maxValue: overallValue,
                    minValue: 0,
                }}
                bg={bg}
                tooltip={getOverallAggregationTooltip(allAggregationsLabel, overallValue)}
            />
        </td>
    )
}

function renderColumnsAggregationCells(
    columnsAggregations: number[],
    columnLabels: string[],
    maxColumnAggregation: number,
    minColumnAggregation: number,
    fontSize: number,
    bg: string,
    allAggregationsLabel: string,
    getColumnAggregationTooltip: (columnAggregationLabel: string, columnLabel: string, value: number) => string
): JSX.Element[] {
    return columnLabels.map((columnLabel, index) => (
        <td key={index}>
            <CalendarHeatMapCell
                fontSize={fontSize}
                values={{
                    value: columnsAggregations[index],
                    maxValue: maxColumnAggregation,
                    minValue: minColumnAggregation,
                }}
                bg={bg}
                tooltip={getColumnAggregationTooltip(allAggregationsLabel, columnLabel, columnsAggregations[index])}
            />
        </td>
    ))
}

function renderRowsAggregationCell(
    values: HeatMapValues,
    rowLabel: string,
    fontSize: number,
    bg: string,
    allAggregationsLabel: string,
    getRowAggregationTooltip: (rowAggregationLabel: string, rowLabel: string, value: number) => string
): JSX.Element {
    return (
        <td className="aggregation-border">
            <CalendarHeatMapCell
                fontSize={fontSize}
                values={values}
                bg={bg}
                tooltip={getRowAggregationTooltip(allAggregationsLabel, rowLabel, values.value)}
            />
        </td>
    )
}

function renderDataCells(
    columnLabels: string[],
    rowData: number[],
    maxValue: number,
    minValue: number,
    rowLabel: string,
    fontSize: number,
    bg: string,
    getDataTooltip: (rowLabel: string, columnLabel: string, value: number) => string
): JSX.Element[] {
    return columnLabels.map((columnLabel, index) => (
        <td key={index}>
            <CalendarHeatMapCell
                fontSize={fontSize}
                values={{
                    value: rowData[index],
                    maxValue,
                    minValue,
                }}
                bg={bg}
                tooltip={getDataTooltip(rowLabel, columnLabel, rowData[index])}
            />
        </td>
    ))
}
