import { BreakdownFilter, CompareFilter, DateRange, VizSpecificOptions } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { IndexedTrendResult } from '../../../../trends/types'

export type DisplayValidationInput = {
    display?: ChartDisplayType | null
    isTrends: boolean
    dateRange?: DateRange | null
    series?: unknown[] | null
    breakdownFilter?: BreakdownFilter | null
    compareFilter?: CompareFilter | null
    hasFormula: boolean
}

export type ChangeDirection = 'up' | 'down' | 'flat' | 'unavailable'
export type ChangeChartDisplayMode = 'relative' | 'absolute'
export type ChangeChartOrderBy = 'change' | 'name' | 'currentValue' | 'previousValue'
export type ChangeChartOrderDirection = 'asc' | 'desc'
export type ChangeChartVizOptions = NonNullable<VizSpecificOptions[ChartDisplayType.ChangeChart]>

export type ChangeChartRow = {
    breakdownValue: IndexedTrendResult['breakdown_value']
    current: IndexedTrendResult | null
    previous: IndexedTrendResult | null
    currentValue: number
    previousValue: number | null
    absoluteChange: number | null
    percentChange: number | null
    direction: ChangeDirection
    sortValue: number
}

export const DEFAULT_CHANGE_CHART_VIZ_OPTIONS: ChangeChartVizOptions = {
    displayMode: 'relative',
    orderBy: 'change',
    orderDirection: 'desc',
    showCurrentValue: true,
}

export function getChangeChartVizOptions(
    vizSpecificOptions: VizSpecificOptions | null | undefined
): ChangeChartVizOptions {
    return {
        ...DEFAULT_CHANGE_CHART_VIZ_OPTIONS,
        ...vizSpecificOptions?.[ChartDisplayType.ChangeChart],
    }
}

export function isChangeChartDisplay(display?: ChartDisplayType | null): boolean {
    return display === ChartDisplayType.ChangeChart
}

export function hasSingleChangeChartBreakdown(breakdownFilter?: BreakdownFilter | null): boolean {
    if (!breakdownFilter) {
        return false
    }

    if (breakdownFilter.breakdowns) {
        return breakdownFilter.breakdowns.length === 1
    }

    return breakdownFilter.breakdown !== undefined && breakdownFilter.breakdown !== null
}

export function getChangeChartValidationError({
    display,
    isTrends,
    dateRange,
    series,
    breakdownFilter,
    compareFilter,
    hasFormula,
}: DisplayValidationInput): string | null {
    if (!isChangeChartDisplay(display)) {
        return null
    }

    if (!isTrends) {
        return 'Change chart is only available for Trends insights.'
    }

    if (dateRange?.date_from === 'all') {
        return 'Change chart requires a finite date range and does not support all time.'
    }

    if ((series?.length ?? 0) !== 1) {
        return 'Change chart requires exactly one series.'
    }

    if (hasFormula) {
        return 'Change chart does not support formulas.'
    }

    if (!hasSingleChangeChartBreakdown(breakdownFilter)) {
        return 'Change chart requires exactly one breakdown.'
    }

    if (!compareFilter?.compare) {
        return 'Change chart requires comparison with the previous period.'
    }

    return null
}

export function getDisplayValidationError(input: DisplayValidationInput): string | null {
    if (isChangeChartDisplay(input.display)) {
        return getChangeChartValidationError(input)
    }

    return null
}

const RELATIVE_TIME_RANGE_RE = /^-\d+(s|m|h)$/

export function shouldForceExactDateRangeForChangeChart(dateRange?: DateRange | null): boolean {
    if (!dateRange) {
        return false
    }

    if (dateRange.explicitDate) {
        return true
    }

    return [dateRange.date_from, dateRange.date_to].some(
        (value): value is string => typeof value === 'string' && RELATIVE_TIME_RANGE_RE.test(value)
    )
}

const stringifyBreakdownValue = (breakdownValue: IndexedTrendResult['breakdown_value']): string => {
    return JSON.stringify(breakdownValue ?? null)
}

function getResultValue(result: IndexedTrendResult | null): number | null {
    if (!result) {
        return null
    }

    if (Number.isFinite(result.aggregated_value)) {
        return result.aggregated_value
    }

    if (Number.isFinite(result.count)) {
        return result.count
    }

    return null
}

export function buildChangeChartRows(results: IndexedTrendResult[]): ChangeChartRow[] {
    const rows = new Map<string, ChangeChartRow>()

    for (const result of results) {
        const key = stringifyBreakdownValue(result.breakdown_value)
        const existing =
            rows.get(key) ??
            ({
                breakdownValue: result.breakdown_value,
                current: null,
                previous: null,
                currentValue: 0,
                previousValue: null,
                absoluteChange: null,
                percentChange: null,
                direction: 'unavailable',
                sortValue: Number.NEGATIVE_INFINITY,
            } satisfies ChangeChartRow)

        if (result.compare_label === 'previous') {
            existing.previous = result
        } else {
            existing.current = result
        }

        rows.set(key, existing)
    }

    return Array.from(rows.values()).map((row) => {
        const currentValue = getResultValue(row.current) ?? 0
        const previousValue = row.previous ? getResultValue(row.previous) : row.current ? 0 : null

        let absoluteChange: number | null = null
        let percentChange: number | null = null
        let direction: ChangeDirection = 'unavailable'
        let sortValue = Number.NEGATIVE_INFINITY

        if (previousValue === null) {
            absoluteChange = null
            percentChange = null
            direction = 'unavailable'
        } else {
            absoluteChange = currentValue - previousValue

            if (previousValue === 0) {
                if (currentValue > 0) {
                    percentChange = Number.POSITIVE_INFINITY
                    direction = 'up'
                    sortValue = Number.POSITIVE_INFINITY
                } else {
                    percentChange = 0
                    direction = 'flat'
                    sortValue = 0
                }
            } else {
                percentChange = ((currentValue - previousValue) / Math.abs(previousValue)) * 100
                if (percentChange > 0) {
                    direction = 'up'
                } else if (percentChange < 0) {
                    direction = 'down'
                } else {
                    direction = 'flat'
                }
                sortValue = percentChange
            }
        }

        return {
            ...row,
            currentValue,
            previousValue,
            absoluteChange,
            percentChange,
            direction,
            sortValue,
        }
    })
}

export function getChangeChartDisplayValue(row: ChangeChartRow, displayMode: ChangeChartDisplayMode): number | null {
    return displayMode === 'absolute' ? row.absoluteChange : row.percentChange
}

export function sortChangeChartRows(
    rows: ChangeChartRow[],
    options: Pick<ChangeChartVizOptions, 'displayMode' | 'orderBy' | 'orderDirection'>,
    getLabel: (row: ChangeChartRow) => string
): ChangeChartRow[] {
    const directionMultiplier = options.orderDirection === 'asc' ? 1 : -1

    return [...rows].sort((left, right) => {
        if (options.orderBy === 'name') {
            return (
                getLabel(left).localeCompare(getLabel(right), undefined, { sensitivity: 'base' }) * directionMultiplier
            )
        }

        const numericValue = (row: ChangeChartRow): number | null => {
            if (options.orderBy === 'currentValue') {
                return row.currentValue
            }
            if (options.orderBy === 'previousValue') {
                return row.previousValue
            }

            return getChangeChartDisplayValue(row, options.displayMode)
        }

        const leftValue = numericValue(left)
        const rightValue = numericValue(right)

        if (leftValue === null && rightValue === null) {
            return getLabel(left).localeCompare(getLabel(right), undefined, { sensitivity: 'base' })
        }

        if (leftValue === null) {
            return 1
        }

        if (rightValue === null) {
            return -1
        }

        if (leftValue !== rightValue) {
            return (leftValue - rightValue) * directionMultiplier
        }

        return getLabel(left).localeCompare(getLabel(right), undefined, { sensitivity: 'base' }) * directionMultiplier
    })
}

export function getChangeChartDomain(rows: ChangeChartRow[], displayMode: ChangeChartDisplayMode): number {
    const finiteMax = rows.reduce((max, row) => {
        const value = getChangeChartDisplayValue(row, displayMode)
        if (value === null || !Number.isFinite(value)) {
            return max
        }
        return Math.max(max, Math.abs(value))
    }, 0)

    const target = Math.max(finiteMax, displayMode === 'absolute' ? 1 : 20)
    if (displayMode === 'absolute') {
        return Math.ceil(target)
    }
    return Math.ceil(target / 20) * 20
}

export function getChangeChartBarWidthPercent(
    row: ChangeChartRow,
    domain: number,
    displayMode: ChangeChartDisplayMode
): number {
    const value = getChangeChartDisplayValue(row, displayMode)
    if (value === null) {
        return 0
    }

    if (!Number.isFinite(value)) {
        return 50
    }

    return Math.min((Math.abs(value) / domain) * 50, 50)
}

export function formatChangeChartPercent(value: number | null): string {
    if (value === null || Number.isNaN(value)) {
        return 'No previous data'
    }

    if (value === Number.POSITIVE_INFINITY) {
        return 'New'
    }

    if (value === Number.NEGATIVE_INFINITY) {
        return '-inf%'
    }

    const sign = value > 0 ? '+' : ''
    const absValue = Math.abs(value)
    const formatted =
        absValue >= 10 || Number.isInteger(absValue)
            ? absValue.toFixed(absValue % 1 === 0 ? 0 : 1)
            : absValue.toFixed(1)

    if (value === 0) {
        return '0%'
    }

    return `${sign}${value < 0 ? '-' : ''}${formatted}%`
}
