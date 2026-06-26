import type { ChartSpec, ChartSpecConfig } from 'lib/components/ChartSpecRenderer/chartSpec'

// The mapping the backend returns: result columns assigned to chart roles. The actual data stays
// client-side — we combine this with the query's rows to build a renderable inline `ChartSpec`.
export interface ChartSpecMappingSeries {
    column: string
    label?: string
    type?: 'line' | 'bar' | 'area'
    axis?: 'left' | 'right'
}

export interface ChartSpecMappingAxis {
    id: 'left' | 'right'
    label?: string
    format?: 'numeric' | 'short' | 'percentage' | 'percentage_scaled' | 'currency' | 'duration' | 'duration_ms'
    currency?: string
    scale?: 'linear' | 'log'
    startAtZero?: boolean
}

export interface ChartSpecMappingReferenceLine {
    value: number | string
    orientation?: 'horizontal' | 'vertical'
    label?: string
    variant?: 'goal' | 'alert' | 'marker'
    axis?: 'left' | 'right'
}

export interface ChartSpecMapping {
    chartType: ChartSpec['chartType']
    title?: string
    narrative?: string
    xColumn: string
    series: ChartSpecMappingSeries[]
    axes?: ChartSpecMappingAxis[]
    config?: ChartSpecConfig
    referenceLines?: ChartSpecMappingReferenceLine[]
}

function toNumber(value: unknown): number {
    const n = typeof value === 'number' ? value : Number(value)
    return Number.isFinite(n) ? n : 0
}

function toLabel(value: unknown): string {
    return value == null ? '' : String(value)
}

/** Build a renderable `ChartSpec` from the backend mapping and the actual query result rows.
 *  Returns null when the mapped x column isn't present (e.g. the query changed since generation). */
export function chartSpecFromMapping(
    mapping: ChartSpecMapping,
    columns: string[],
    rows: unknown[][]
): ChartSpec | null {
    const indexOf = (name: string): number => columns.indexOf(name)

    const xIndex = indexOf(mapping.xColumn)
    if (xIndex < 0) {
        return null
    }

    const labels = rows.map((row) => toLabel(row[xIndex]))

    const series = mapping.series
        .map((s) => ({ s, i: indexOf(s.column) }))
        .filter(({ i }) => i >= 0)
        .map(({ s, i }) => ({
            key: s.column,
            label: s.label ?? s.column,
            data: rows.map((row) => toNumber(row[i])),
            type: s.type,
            axis: s.axis,
        }))

    if (series.length === 0) {
        return null
    }

    return {
        chartType: mapping.chartType,
        title: mapping.title,
        narrative: mapping.narrative,
        labels,
        series,
        axes: mapping.axes,
        config: mapping.config,
        referenceLines: mapping.referenceLines,
    }
}
