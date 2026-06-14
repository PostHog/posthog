import type { LegendItem } from '../../components/Legend/Legend'
import { legendItemsFromSeries } from '../../components/Legend/legendItemsFromSeries'
import type { ChartTheme, ResolvedSeries, Series } from '../../core/types'
import { slopeDelta } from './slope-data'

/** Legend items for a slope chart — `legendItemsFromSeries` plus a per-series change
 *  (`end − start`, formatted) carried as each row's `secondaryLabel`. */
export function slopeLegendItems(
    series: ReadonlyArray<Series | ResolvedSeries>,
    theme: ChartTheme,
    deltaFormatter: (delta: number) => string
): LegendItem[] {
    const byKey = new Map(series.map((s) => [s.key, s]))
    return legendItemsFromSeries(series, theme).map((item) => ({
        ...item,
        secondaryLabel: deltaFormatter(slopeDelta(byKey.get(item.key)!)),
    }))
}
