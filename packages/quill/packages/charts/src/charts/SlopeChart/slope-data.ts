import type { Series } from '../../core/types'

/** Per-series options read from `Series.meta` by the slope chart. Lets a consumer toggle the
 *  start/end value labels for an individual series without touching the shared `Series` type. */
export interface SlopeSeriesMeta {
    /** Show this series' start (left) value label. Falls back to the chart-level default. */
    showStartLabel?: boolean
    /** Show this series' end (right) value label. Falls back to the chart-level default. */
    showEndLabel?: boolean
}

/** A slope chart series carries exactly two values — `[start, end]`. These helpers read them
 *  defensively (first and last entry) so a malformed series degrades gracefully. */
export function slopeStart(series: Pick<Series, 'data'>): number {
    return series.data[0] ?? 0
}

export function slopeEnd(series: Pick<Series, 'data'>): number {
    return series.data[series.data.length - 1] ?? 0
}

export function slopeDelta(series: Pick<Series, 'data'>): number {
    return slopeEnd(series) - slopeStart(series)
}

export function defaultValueFormatter(value: number): string {
    return value.toLocaleString()
}

export function defaultDeltaFormatter(delta: number): string {
    const sign = delta > 0 ? '+' : ''
    return `${sign}${delta.toLocaleString()}`
}
