import { getSeriesColor } from 'lib/colors'
import { dayjs } from 'lib/dayjs'

import { ScatterSettings } from '~/queries/schema/schema-general'

import { Column } from '../../../dataVisualizationLogic'

/** Results are LIMIT-capped upstream, but a huge query can still return more dots than Chart.js
 *  handles smoothly - cap and surface the truncation instead of freezing the tab. */
export const SCATTER_MAX_POINTS = 10000
export const SCATTER_MAX_SERIES = 10
export const SCATTER_OTHER_SERIES_LABEL = 'Other'

export interface ScatterPoint {
    x: number
    y: number
    /** Index into the raw response rows, so hover/click can surface the full row. */
    rowIndex: number
}

export interface ScatterSeries {
    label: string
    color: string
    points: ScatterPoint[]
}

export interface ScatterChartData {
    series: ScatterSeries[]
    /** Rows skipped for a null/non-numeric x or y, or a non-positive y on a log scale. */
    hiddenPointCount: number
    truncated: boolean
    xIsDate: boolean
}

const isDateType = (column: Column): boolean => column.type.name === 'DATE' || column.type.name === 'DATETIME'

const parseNumeric = (value: unknown): number | null => {
    // Only numbers and numeric strings plot; Infinity breaks Chart.js axis scaling,
    // and arrays/booleans would coerce into misleading dots.
    if (typeof value !== 'number' && typeof value !== 'string') {
        return null
    }
    if (value === '') {
        return null
    }
    const numericValue = Number(value)
    return Number.isFinite(numericValue) ? numericValue : null
}

const parseX = (value: unknown, xIsDate: boolean): number | null => {
    if (!xIsDate) {
        return parseNumeric(value)
    }
    if (value === null || value === undefined || value === '') {
        return null
    }
    const parsed = dayjs(value as string | number | Date)
    return parsed.isValid() ? parsed.valueOf() : null
}

export const buildScatterChartData = (
    rows: any[][],
    columns: Column[],
    settings: ScatterSettings
): ScatterChartData | null => {
    const xColumn = columns.find((column) => column.name === settings.xAxisColumn)
    const yColumn = columns.find((column) => column.name === settings.yAxisColumn)
    if (!xColumn || !yColumn) {
        return null
    }

    const colorByColumn = settings.colorByColumn
        ? columns.find((column) => column.name === settings.colorByColumn)
        : undefined
    const xIsDate = isDateType(xColumn)
    const logY = settings.yAxisScale === 'logarithmic'

    const pointsByGroup = new Map<string, ScatterPoint[]>()
    let hiddenPointCount = 0
    let plottedCount = 0
    let truncated = false

    for (let rowIndex = 0; rowIndex < rows.length; rowIndex++) {
        const row = rows[rowIndex]
        const x = parseX(row[xColumn.dataIndex], xIsDate)
        const y = parseNumeric(row[yColumn.dataIndex])

        if (x === null || y === null || (logY && y <= 0)) {
            hiddenPointCount += 1
            continue
        }

        if (plottedCount >= SCATTER_MAX_POINTS) {
            truncated = true
            break
        }
        plottedCount += 1

        const groupValue = colorByColumn ? row[colorByColumn.dataIndex] : undefined
        const groupLabel = colorByColumn
            ? groupValue === null || groupValue === undefined
                ? 'null'
                : String(groupValue)
            : yColumn.name
        const group = pointsByGroup.get(groupLabel)
        if (group) {
            group.push({ x, y, rowIndex })
        } else {
            pointsByGroup.set(groupLabel, [{ x, y, rowIndex }])
        }
    }

    // Cap legend cardinality: keep the largest groups, fold the tail into one "Other" series.
    const groups = Array.from(pointsByGroup.entries()).sort((a, b) => b[1].length - a[1].length)
    let keptGroups = groups
    if (groups.length > SCATTER_MAX_SERIES) {
        keptGroups = groups.slice(0, SCATTER_MAX_SERIES - 1)
        const otherPoints = groups.slice(SCATTER_MAX_SERIES - 1).flatMap(([, points]) => points)
        keptGroups.push([SCATTER_OTHER_SERIES_LABEL, otherPoints])
    }

    return {
        series: keptGroups.map(([label, points], index) => ({
            label,
            color: getSeriesColor(index),
            points,
        })),
        hiddenPointCount,
        truncated,
        xIsDate,
    }
}
