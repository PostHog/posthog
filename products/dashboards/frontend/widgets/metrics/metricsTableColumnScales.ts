import { metricValuesFormatter } from 'products/metrics/frontend/panels/metricsUnits'

import type { MetricsTableResultColumn, MetricsTableResultRow } from './MetricsTableWidget'

export type MetricsTableSparklineDomain = { min: number; max: number }

/** The range of each column across all rows, so the sparklines in one column share a scale. Zero stays in the range. */
export function metricsTableSparklineDomains(
    rows: MetricsTableResultRow[],
    columnCount: number
): MetricsTableSparklineDomain[] {
    return Array.from({ length: columnCount }, (_, index) => {
        const values = rows.flatMap((row) => (row.sparklines[index] ?? []).map((point) => point ?? 0))
        return { min: Math.min(0, ...values), max: Math.max(0, ...values) }
    })
}

/** SVG coordinates for a sparkline. A missing point draws at zero. */
export function metricsTableSparklineCoordinates(
    points: (number | null)[],
    { min, max }: MetricsTableSparklineDomain,
    { width, height }: { width: number; height: number }
): [number, number][] {
    const step = points.length > 1 ? width / (points.length - 1) : 0
    const scale = max > min ? (height - 2) / (max - min) : 0
    return points.map((point, index) => [index * step, height - 1 - ((point ?? 0) - min) * scale])
}

/** One value formatter per column. A dimensionless column then shows every row as a percent, or none of them. */
export function metricsTableColumnFormatters(
    rows: MetricsTableResultRow[],
    columns: MetricsTableResultColumn[]
): ((value: number) => string)[] {
    return columns.map((column, index) =>
        metricValuesFormatter(
            column.unit ?? undefined,
            rows.map((row) => row.values[index]).filter((value): value is number => value != null)
        )
    )
}
