import type { ChartTheme, ResolvedSeries, Series } from '../../core/types'
import type { LegendItem } from './Legend'

export interface LegendItemsFromSeriesOptions {
    /** Include `overlay: true` series (trendlines, moving averages). Defaults to `false` —
     *  overlays would otherwise produce near-duplicate legend rows alongside their primary series. */
    includeOverlay?: boolean
}

export function legendItemsFromSeries(
    series: ReadonlyArray<Series | ResolvedSeries>,
    theme: ChartTheme,
    options: LegendItemsFromSeriesOptions = {}
): LegendItem[] {
    const { includeOverlay = false } = options
    const palette = theme.colors
    const items: LegendItem[] = []
    for (let i = 0; i < series.length; i++) {
        const s = series[i]
        if (s.visibility?.excluded) {
            continue
        }
        if (s.overlay && !includeOverlay) {
            continue
        }
        const fallback = palette.length > 0 ? palette[i % palette.length] : '#000'
        items.push({ key: s.key, label: s.label, color: s.color ?? fallback })
    }
    return items
}
