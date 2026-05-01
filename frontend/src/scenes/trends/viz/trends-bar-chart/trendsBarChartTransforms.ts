import type { Series } from 'lib/hog-charts'
import { hexToRGBA } from 'lib/utils'

const COMPARE_PREVIOUS_DIM_OPACITY = 0.5

// Shape both IndexedTrendResult (kea) and TrendsResultItem (MCP) satisfy.
export interface TrendsBarResultLike {
    id?: string | number
    label?: string | null
    data: number[]
    aggregated_value?: number
    days?: string[]
    compare?: boolean
    compare_label?: string | null
    action?: { order?: number } | null
    breakdown_value?: unknown
    filter?: unknown
}

export interface BuildTrendsBarSeriesOpts<R extends TrendsBarResultLike, M = unknown> {
    getColor: (r: R, index: number) => string
    getHidden?: (r: R, index: number) => boolean
    buildMeta?: (r: R, index: number) => M
}

export function buildTrendsBarTimeSeries<R extends TrendsBarResultLike, M = unknown>(
    results: R[],
    opts: BuildTrendsBarSeriesOpts<R, M>
): Series<M>[] {
    return results.map((r, index) => {
        const baseColor = opts.getColor(r, index)
        const color = r.compare_label === 'previous' ? hexToRGBA(baseColor, COMPARE_PREVIOUS_DIM_OPACITY) : baseColor
        const excluded = opts.getHidden ? opts.getHidden(r, index) : false
        const meta = opts.buildMeta ? opts.buildMeta(r, index) : undefined
        return {
            key: String(r.id),
            label: r.label ?? '',
            data: r.data,
            color,
            meta,
            visibility: excluded ? { excluded: true } : undefined,
        }
    })
}
