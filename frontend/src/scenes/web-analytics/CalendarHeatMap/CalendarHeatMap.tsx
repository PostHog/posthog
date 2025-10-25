import './CalendarHeatMap.scss'

import { useValues } from 'kea'
import React, { useCallback, useEffect, useState } from 'react'

import { LemonSkeleton, Tooltip } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
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
    showRowAggregations?: boolean
    showColumnAggregations?: boolean
    getOnClickTooltip?: (colIndex: number, rowIndex?: number) => string
    onClick?: (colIndex: number, rowIndex?: number) => void
    /**
     * When providing an onClick function, you may not want all cells to be clickable - e.g., if value is 0
     * If onClick is provided and isClickable is not, then all cells are clickable
     */
    isClickable?: (colIndex: number, rowIndex?: number) => boolean
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
    showRowAggregations = true,
    showColumnAggregations = true,
    getOnClickTooltip,
    onClick,
    isClickable,
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
                            {columnLabels.map((label, i) => {
                                const cellIsClickable = onClick && (isClickable?.(i) ?? true)
                                const headerContents = cellIsClickable ? (
                                    <Tooltip title={getOnClickTooltip ? getOnClickTooltip(i) : ''} delayMs={100}>
                                        {label}
                                    </Tooltip>
                                ) : (
                                    label
                                )
                                return (
                                    <th
                                        key={i}
                                        className={cn(
                                            cellIsClickable ? 'rounded cursor-pointer hover:bg-highlight' : ''
                                        )}
                                        onClick={
                                            cellIsClickable
                                                ? () => {
                                                      onClick(i)
                                                  }
                                                : undefined
                                        }
                                    >
                                        {headerContents}
                                    </th>
                                )
                            })}
                            {rowsAggregations?.[0] !== undefined && showRowAggregations && (
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
                        {rowLabels.map((rowLabel, rowIndex) => (
                            <tr key={rowIndex}>
                                <td className="CalendarHeatMap__TextTab">{rowLabel}</td>
                                {renderDataCells(
                                    columnLabels,
                                    matrix[rowIndex],
                                    maxOverall,
                                    minOverall,
                                    rowLabel,
                                    fontSize,
                                    heatmapColor,
                                    getDataTooltip,
                                    onClick && getOnClickTooltip
                                        ? (colIndex: number) => getOnClickTooltip?.(colIndex, rowIndex)
                                        : undefined,
                                    onClick ? (colIndex: number) => onClick(colIndex, rowIndex) : undefined,
                                    isClickable ? (colIndex: number) => isClickable(colIndex, rowIndex) : undefined
                                )}
                                {showRowAggregations &&
                                    renderRowsAggregationCell(
                                        {
                                            value: rowsAggregations[rowIndex],
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
                        {showColumnAggregations && (
                            <tr className="aggregation-border" data-attr="column-aggregations">
                                {columnsAggregations?.[0] !== undefined && (
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
                                {showColumnAggregations &&
                                    showRowAggregations &&
                                    renderOverallCell(
                                        overallValue,
                                        fontSize,
                                        backgroundColorOverall,
                                        allAggregationsLabel,
                                        getOverallAggregationTooltip
                                    )}
                            </tr>
                        )}
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
    getDataTooltip: (rowLabel: string, columnLabel: string, value: number) => string,
    // on click and getonClickToolTip don't take params here to avoid having to pass more info down
    getOnClickTooltip?: (colIndex: number) => string,
    onClick?: (colIndex: number) => void,
    isClickable?: (colIndex: number) => boolean
): JSX.Element[] {
    return columnLabels.map((columnLabel, index) => {
        const isClickableCell = onClick && (isClickable?.(index) ?? true)
        return (
            <td key={index}>
                <CalendarHeatMapCell
                    fontSize={fontSize}
                    values={{
                        value: rowData?.[index] ?? 0,
                        maxValue,
                        minValue,
                    }}
                    bg={bg}
                    tooltip={
                        isClickableCell && getOnClickTooltip
                            ? getOnClickTooltip(index)
                            : getDataTooltip(rowLabel, columnLabel, rowData?.[index] ?? 0)
                    }
                    onClick={isClickableCell ? () => onClick(index) : undefined}
                />
            </td>
        )
    })
}
