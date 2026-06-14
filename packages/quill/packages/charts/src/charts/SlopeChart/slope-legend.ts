import type { LegendItem } from '../../components/Legend/Legend'
import type { ChartTheme, ResolvedSeries, Series } from '../../core/types'
import { slopeDelta } from './slope-data'

/** Legend items for a slope chart — like `legendItemsFromSeries`, but each row also carries the
 *  per-series change (`end − start`, formatted) as its `secondaryLabel`. Color falls back to the
 *  palette by original index, matching the chart's color assignment. */
export function slopeLegendItems(
    series: ReadonlyArray<Series | ResolvedSeries>,
    theme: ChartTheme,
    deltaFormatter: (delta: number) => string
): LegendItem[] {
    const palette = theme.colors
    const items: LegendItem[] = []
    for (let i = 0; i < series.length; i++) {
        const s = series[i]
        if (s.visibility?.excluded) {
            continue
        }
        const fallback = palette.length > 0 ? palette[i % palette.length] : '#000'
        items.push({
            key: s.key,
            label: s.label,
            color: s.color || fallback,
            secondaryLabel: deltaFormatter(slopeDelta(s)),
        })
    }
    return items
}
