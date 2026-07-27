import type { ChartTheme, ResolvedSeries, Series } from '../../core/types'
import type { LegendItem } from './Legend'

export function legendItemsFromSeries(series: ReadonlyArray<Series | ResolvedSeries>, theme: ChartTheme): LegendItem[] {
    const palette = theme.colors
    const items: LegendItem[] = []
    for (let i = 0; i < series.length; i++) {
        const s = series[i]
        if (s.visibility?.excluded) {
            continue
        }
        const fallback = palette.length > 0 ? palette[i % palette.length] : '#000'
        items.push({ key: s.key, label: s.label, color: s.color || fallback })
    }
    return items
}
