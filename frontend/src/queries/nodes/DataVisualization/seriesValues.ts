import { ChartSettingsFormatting } from '~/queries/schema/schema-general'

/**
 * Parses a raw result cell into a chart value, with the series formatting applied.
 * An empty cell, or a cell that does not hold a number, gives null.
 */
function parseSeriesValue(value: unknown, formatting?: ChartSettingsFormatting): number | null {
    if (value === undefined || value === null || Number.isNaN(value)) {
        return null
    }

    try {
        const multiplier = formatting?.style === 'percent' ? 100 : 1

        if (formatting?.decimalPlaces) {
            const parsed = parseFloat((parseFloat(String(value)) * multiplier).toFixed(formatting.decimalPlaces))
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

/**
 * Adds up one column across the rows behind a single chart point. A point with no number in it
 * stays empty, so the chart hides it, unless the chart asks to show an empty point as zero.
 */
export function sumSeriesValues(
    rows: any[],
    dataIndex: number,
    formatting: ChartSettingsFormatting | undefined,
    showNullsAsZero: boolean
): number | null {
    let total = 0
    let hasValue = false

    for (const row of rows) {
        const value = parseSeriesValue(row[dataIndex], formatting)
        if (value !== null) {
            total += value
            hasValue = true
        }
    }

    if (!hasValue) {
        return showNullsAsZero ? 0 : null
    }

    return total
}
