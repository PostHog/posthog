import type { AnomalyPoint } from 'lib/components/Alerts/types'

import type { IndexedTrendResult } from '../../types'

export interface AnomalyMarker {
    /** Index along the x-axis (into the chart's `labels` array). */
    dataIndex: number
    /** y-value at the marker (used to position via the y-scale). */
    value: number
    /** Color to fill the marker (typically the source series's color). */
    color: string
    /** Originating alert anomaly score (0..1) if available. */
    score: number | null
    /** y-axis id the marker is positioned against. */
    yAxisId: string
}

/** Build a flat list of {@link AnomalyMarker}s ready for rendering as DOM dots.
 *
 *  Mirrors the legacy LineGraph.tsx logic: each anomaly carries a `seriesIndex`
 *  (the source `IndexedTrendResult.seriesIndex`, set per-alert via `alert.config.series_index`).
 *  We match by that, then resolve the anomaly's `date` to a chart x-index via the source
 *  result's `days`. Anomalies whose date or series falls outside the current view are dropped.
 *
 *  This is a pure function so it can be unit-tested without rendering. */
export function buildAnomalyMarkers(
    anomalyPoints: AnomalyPoint[] | null | undefined,
    indexedResults: IndexedTrendResult[] | null | undefined,
    getColor: (r: IndexedTrendResult) => string,
    getYAxisId: (r: IndexedTrendResult) => string,
    isHidden: (r: IndexedTrendResult) => boolean
): AnomalyMarker[] {
    if (!anomalyPoints?.length || !indexedResults?.length) {
        return []
    }
    const markers: AnomalyMarker[] = []
    for (const ap of anomalyPoints) {
        const result = indexedResults.find((r) => r.seriesIndex === ap.seriesIndex)
        if (!result || isHidden(result)) {
            continue
        }
        const days: string[] = result.action?.days ?? result.days ?? []
        if (!days.length) {
            continue
        }
        const dataIndex = days.indexOf(ap.date)
        if (dataIndex < 0 || dataIndex >= result.data.length) {
            continue
        }
        const value = Number(result.data[dataIndex])
        if (!Number.isFinite(value)) {
            continue
        }
        markers.push({
            dataIndex,
            value,
            color: getColor(result),
            score: ap.score,
            yAxisId: getYAxisId(result),
        })
    }
    return markers
}
