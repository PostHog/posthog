import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import type { Sorting } from 'lib/lemon-ui/LemonTable/sorting'
import { SortingIndicator, getNextSorting } from 'lib/lemon-ui/LemonTable/sorting'
import { InsightEmptyState } from 'scenes/insights/EmptyStates'

import { HeatmapSettings } from '~/queries/schema/schema-general'

import { dataVisualizationLogic } from '../../dataVisualizationLogic'
import {
    buildFallbackGradientStops,
    formatHeatmapLabel,
    formatHeatmapValue,
    getHeatmapNullLabel,
    getHeatmapNullValue,
    getHeatmapTextClassName,
    interpolateHeatmapColor,
    resolveGradientStops,
    stretchGradientStopsToValues,
} from './heatmapUtils'
import {
    getHeatmapSettingsWithSorting,
    getSortingFromHeatmapSettings,
    HEATMAP_ROW_LABEL_SORT_KEY,
    sortHeatmapRows,
} from './twoDimensionalHeatmapUtils'

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

type HeatmapDataSettings = Pick<
    HeatmapSettings,
    'xAxisColumn' | 'yAxisColumn' | 'valueColumn' | 'nullLabel' | 'nullValue'
>

const buildHeatmapData = (
    rows: any[],
    heatmapSettings: HeatmapDataSettings,
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
    const nullLabel = getHeatmapNullLabel(heatmapSettings)

    rows.forEach((row) => {
        const xLabel = formatHeatmapLabel(row[xIndex], nullLabel)
        const yLabel = formatHeatmapLabel(row[yIndex], nullLabel)
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

const getAriaSort = (order: Sorting['order'] | null): 'ascending' | 'descending' | 'none' => {
    if (order === 1) {
        return 'ascending'
    }

    if (order === -1) {
        return 'descending'
    }

    return 'none'
}

const getNextSortingTitle = (currentSorting: Sorting | null, columnKey: string, defaultSortOrder: 1 | -1): string => {
    const nextSorting = getNextSorting(currentSorting, columnKey, false, defaultSortOrder)

    if (!nextSorting) {
        return 'Click to cancel sorting'
    }

    return `Click to sort rows ${nextSorting.order === 1 ? 'ascending' : 'descending'}`
}

export function TwoDimensionalHeatmap({ allowSorting = true }: { allowSorting?: boolean }): JSX.Element {
    const { response, columns, chartSettings } = useValues(dataVisualizationLogic)
    const { updateChartSettings } = useActions(dataVisualizationLogic)

    const heatmapSettings = chartSettings.heatmap ?? {}
    const { xAxisColumn, yAxisColumn, valueColumn, nullLabel, nullValue } = heatmapSettings
    const sorting = useMemo(
        () => getSortingFromHeatmapSettings(heatmapSettings),
        [heatmapSettings.sortColumn, heatmapSettings.sortOrder, heatmapSettings]
    )
    const selectedColumns = [xAxisColumn, yAxisColumn, valueColumn]
    const rows =
        response && 'results' in response ? response.results : response && 'result' in response ? response.result : []
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

        return buildHeatmapData(rows, { xAxisColumn, yAxisColumn, valueColumn, nullLabel, nullValue }, columnIndexes)
    }, [
        rows,
        hasSelection,
        hasValidColumns,
        xAxisColumn,
        yAxisColumn,
        valueColumn,
        nullLabel,
        nullValue,
        columnIndexes,
    ])

    useEffect(() => {
        if (
            sorting &&
            sorting.columnKey !== HEATMAP_ROW_LABEL_SORT_KEY &&
            !heatmapData.xValues.includes(sorting.columnKey)
        ) {
            updateChartSettings({ heatmap: getHeatmapSettingsWithSorting(heatmapSettings, null) })
        }
    }, [heatmapData.xValues, heatmapSettings, sorting, updateChartSettings])

    const sortedYValues = useMemo(
        () => sortHeatmapRows(heatmapData.yValues, heatmapData.cellValues, sorting),
        [heatmapData.cellValues, heatmapData.yValues, sorting]
    )

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
    const nullValueDisplay = getHeatmapNullValue(heatmapSettings)

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
                            <th
                                className="sticky left-0 z-10 bg-surface-primary border border-border px-2 py-1 text-left"
                                aria-sort={
                                    allowSorting
                                        ? getAriaSort(
                                              sorting?.columnKey === HEATMAP_ROW_LABEL_SORT_KEY ? sorting.order : null
                                          )
                                        : undefined
                                }
                            >
                                {allowSorting ? (
                                    <button
                                        type="button"
                                        className={clsx(
                                            'flex w-full min-w-0 items-center justify-between gap-1 text-left',
                                            sorting?.columnKey === HEATMAP_ROW_LABEL_SORT_KEY && 'font-medium'
                                        )}
                                        onClick={() =>
                                            updateChartSettings({
                                                heatmap: getHeatmapSettingsWithSorting(
                                                    heatmapSettings,
                                                    getNextSorting(sorting, HEATMAP_ROW_LABEL_SORT_KEY, false, 1)
                                                ),
                                            })
                                        }
                                        title={getNextSortingTitle(sorting, HEATMAP_ROW_LABEL_SORT_KEY, 1)}
                                    >
                                        <span className="truncate">{yAxisLabel}</span>
                                        <SortingIndicator
                                            order={
                                                sorting?.columnKey === HEATMAP_ROW_LABEL_SORT_KEY ? sorting.order : null
                                            }
                                        />
                                    </button>
                                ) : (
                                    yAxisLabel
                                )}
                            </th>
                            {heatmapData.xValues.map((xValue, index) => (
                                <th
                                    key={`${xValue}-${index}`}
                                    className="border border-border px-2 py-1 text-left"
                                    aria-sort={
                                        allowSorting
                                            ? getAriaSort(sorting?.columnKey === xValue ? sorting.order : null)
                                            : undefined
                                    }
                                >
                                    {allowSorting ? (
                                        <button
                                            type="button"
                                            className={clsx(
                                                'flex w-full min-w-0 items-center justify-between gap-1 text-left',
                                                sorting?.columnKey === xValue && 'font-medium'
                                            )}
                                            onClick={() =>
                                                updateChartSettings({
                                                    heatmap: getHeatmapSettingsWithSorting(
                                                        heatmapSettings,
                                                        getNextSorting(sorting, xValue, false, -1)
                                                    ),
                                                })
                                            }
                                            title={getNextSortingTitle(sorting, xValue, -1)}
                                        >
                                            <span className="truncate">{xValue}</span>
                                            <SortingIndicator
                                                order={sorting?.columnKey === xValue ? sorting.order : null}
                                            />
                                        </button>
                                    ) : (
                                        xValue
                                    )}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {sortedYValues.map((yValue) => (
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

                                    return (
                                        <td
                                            key={`${yValue}-${xValue}`}
                                            className={clsx(
                                                'border border-border px-2 py-1 text-center',
                                                cellValue !== null && getHeatmapTextClassName(cellColor)
                                            )}
                                            style={{ backgroundColor: cellColor }}
                                        >
                                            {formatHeatmapValue(cellValue, nullValueDisplay)}
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
