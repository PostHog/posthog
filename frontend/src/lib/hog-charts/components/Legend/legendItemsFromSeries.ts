import type { ChartTheme, ResolvedSeries, Series } from '../../core/types'
import type { LegendItem } from './Legend'

/** Map a `Series[]` (or `ResolvedSeries[]`) to `LegendItem[]` using the chart's color-fallback rule.
 *
 *  - Uses `series.color` when set, otherwise picks `theme.colors[index % theme.colors.length]`.
 *  - Drops series with `visibility.excluded === true` — those don't render anywhere in the chart.
 *  - Preserves the input order; the index used for the color fallback is the pre-filter index so
 *    a series' color stays stable regardless of which others are excluded.
 */
export function legendItemsFromSeries(series: ReadonlyArray<Series | ResolvedSeries>, theme: ChartTheme): LegendItem[] {
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
            color: s.color ?? fallback,
        })
    }
    return items
}
