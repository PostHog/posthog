import clsx from 'clsx'
import { useValues } from 'kea'
import { useMemo } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { InsightEmptyState } from 'scenes/insights/EmptyStates'

import { HeatmapSettings } from '~/queries/schema/schema-general'

import { dataVisualizationLogic, formatDataWithSettings } from '../../dataVisualizationLogic'
import {
    buildFallbackGradientStops,
    getHeatmapTextClassName,
    interpolateHeatmapColor,
    resolveGradientStops,
    stretchGradientStopsToValues,
} from './heatmapUtils'

const formatCategoryValue = (value: unknown): string => {
    if (value === null || value === undefined || value === '') {
        return '[No value]'
    }

    return String(value)
}

const parseNumericValue = (value: unknown): number | null => {
    if (value === null || value === undefined || value === '') {
        return null
    }

    const numericValue = Number(value)
    if (Number.isNaN(numericValue)) {
        return null
    }

    return numericValue
}

type HeatmapData = {
    xValues: string[]
    yValues: string[]
    cellValues: Record<string, Record<string, number | null>>
    numericValues: number[]
    duplicateCellCount: number
}

const buildHeatmapData = (
    rows: any[],
    heatmapSettings: HeatmapSettings,
    columnIndexes: Record<string, number>
): HeatmapData => {
    const xValues: string[] = []
    const yValues: string[] = []
    const cellValues: Record<string, Record<string, number | null>> = {}
    const numericValues: number[] = []
    let duplicateCellCount = 0

    const xIndex = columnIndexes[heatmapSettings.xAxisColumn ?? '']
    const yIndex = columnIndexes[heatmapSettings.yAxisColumn ?? '']
    const valueIndex = columnIndexes[heatmapSettings.valueColumn ?? '']

    if (xIndex === undefined || yIndex === undefined || valueIndex === undefined) {
        return {
            xValues,
            yValues,
            cellValues,
            numericValues,
            duplicateCellCount,
        }
    }

    const xIndexMap = new Map<string, number>()
    const yIndexMap = new Map<string, number>()
    const seenCells = new Set<string>()

    rows.forEach((row) => {
        const xLabel = formatCategoryValue(row[xIndex])
        const yLabel = formatCategoryValue(row[yIndex])
        const numericValue = parseNumericValue(row[valueIndex])

        if (!xIndexMap.has(xLabel)) {
            xIndexMap.set(xLabel, xValues.length)
            xValues.push(xLabel)
        }

        if (!yIndexMap.has(yLabel)) {
            yIndexMap.set(yLabel, yValues.length)
            yValues.push(yLabel)
        }

        if (!cellValues[yLabel]) {
            cellValues[yLabel] = {}
        }

        const cellKey = `${yLabel}||${xLabel}`
        if (seenCells.has(cellKey)) {
            duplicateCellCount += 1
        }
        seenCells.add(cellKey)

        cellValues[yLabel][xLabel] = numericValue
    })

    yValues.forEach((yValue) => {
        xValues.forEach((xValue) => {
            const cellValue = cellValues[yValue]?.[xValue]
            if (cellValue !== null && cellValue !== undefined) {
                numericValues.push(cellValue)
            }
        })
    })

    return {
        xValues,
        yValues,
        cellValues,
        numericValues,
        duplicateCellCount,
    }
}

export const TwoDimensionalHeatmap = (): JSX.Element => {
    const { response, columns, chartSettings } = useValues(dataVisualizationLogic)

    const heatmapSettings = chartSettings.heatmap ?? {}
    const selectedColumns = [heatmapSettings.xAxisColumn, heatmapSettings.yAxisColumn, heatmapSettings.valueColumn]
    const rows = response?.['results'] ?? response?.['result'] ?? []
    const columnIndexes = useMemo(() => {
        return columns.reduce(
            (acc, column) => {
                acc[column.name] = column.dataIndex
                return acc
            },
            {} as Record<string, number>
        )
    }, [columns])

    const hasSelection = selectedColumns.every(Boolean)
    const hasValidColumns = selectedColumns.every((columnName) => {
        if (!columnName) {
            return false
        }
        return columnIndexes[columnName] !== undefined
    })

    const heatmapData = useMemo(() => {
        if (!hasSelection || !hasValidColumns) {
            return {
                xValues: [],
                yValues: [],
                cellValues: {},
                numericValues: [],
                duplicateCellCount: 0,
            }
        }

        return buildHeatmapData(rows, heatmapSettings, columnIndexes)
    }, [rows, hasSelection, hasValidColumns, heatmapSettings, columnIndexes])

    const gradientStops = resolveGradientStops(
        chartSettings.heatmap?.gradient,
        buildFallbackGradientStops(heatmapData.numericValues)
    )
    const scaledGradientStops =
        heatmapSettings.gradientScaleMode === 'relative'
            ? stretchGradientStopsToValues(gradientStops, heatmapData.numericValues)
            : gradientStops
    const xAxisLabel = heatmapSettings.xAxisLabel || heatmapSettings.xAxisColumn || 'X-axis'
    const yAxisLabel = heatmapSettings.yAxisLabel || heatmapSettings.yAxisColumn || 'Y-axis'

    if (!hasSelection || !hasValidColumns) {
        return (
            <div className="flex items-center justify-center h-full">
                <InsightEmptyState
                    heading="Select columns to build a 2d heatmap"
                    detail="Choose X-axis, Y-axis, and value columns to render the heatmap."
                />
            </div>
        )
    }

    if (heatmapData.xValues.length === 0 || heatmapData.yValues.length === 0) {
        return (
            <div className="flex items-center justify-center h-full">
                <InsightEmptyState heading="No data for selected columns" detail="" />
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2 p-2">
            {heatmapData.duplicateCellCount > 0 && (
                <LemonBanner type="warning">
                    {`Some rows share the same X/Y combination. Only the latest value is shown for ${heatmapData.duplicateCellCount} duplicate cell${
                        heatmapData.duplicateCellCount === 1 ? '' : 's'
                    }.`}
                </LemonBanner>
            )}
            <div className="text-center text-sm font-medium">{xAxisLabel}</div>
            <div className="overflow-auto">
                <table className="min-w-full border-collapse text-xs">
                    <thead>
                        <tr>
                            <th className="sticky left-0 z-10 bg-surface-primary border border-border px-2 py-1 text-left">
                                {yAxisLabel}
                            </th>
                            {heatmapData.xValues.map((xValue, index) => (
                                <th key={`${xValue}-${index}`} className="border border-border px-2 py-1 text-left">
                                    {xValue}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {heatmapData.yValues.map((yValue) => (
                            <tr key={yValue}>
                                <th className="sticky left-0 z-10 bg-surface-primary border border-border px-2 py-1 text-left">
                                    {yValue}
                                </th>
                                {heatmapData.xValues.map((xValue) => {
                                    const cellValue = heatmapData.cellValues[yValue]?.[xValue] ?? null
                                    const cellColor =
                                        cellValue === null
                                            ? 'transparent'
                                            : interpolateHeatmapColor(cellValue, scaledGradientStops)
                                    const formattedValue = formatDataWithSettings(cellValue, undefined)

                                    return (
                                        <td
                                            key={`${yValue}-${xValue}`}
                                            className={clsx(
                                                'border border-border px-2 py-1 text-center',
                                                cellValue !== null && getHeatmapTextClassName(cellColor)
                                            )}
                                            style={{ backgroundColor: cellColor }}
                                        >
                                            {formattedValue ?? ''}
                                        </td>
                                    )
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </div>
    )
}
