import { ChartSettingsFormatting } from '~/queries/schema/schema-general'

/**
 * Parses a raw result cell into a chart value, with the series formatting applied.
 * An empty cell, or a cell that does not hold a number, gives null so that the chart
 * can either hide the point or show it as zero.
 */
export function parseSeriesValue(value: unknown, formatting?: ChartSettingsFormatting): number | null {
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
