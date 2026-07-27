import type { LegendItem } from '../../components/Legend/Legend'
import { legendItemsFromSeries } from '../../components/Legend/legendItemsFromSeries'
import type { ChartTheme, ResolvedSeries, Series } from '../../core/types'
import { slopeDelta, slopeEnd } from './slope-data'

/** Legend items for a slope chart — `legendItemsFromSeries` plus a per-series change
 *  (`end − start`, formatted) carried as each row's `secondaryLabel`. Rows are ordered
 *  biggest-to-smallest by end value so the legend matches the lines' vertical order at
 *  the right edge (and the tooltip's ordering). Sorting the built items rather than the
 *  input series keeps each swatch's colour — `legendItemsFromSeries` assigns palette
 *  colours by input index — matched to its line. */
export function slopeLegendItems(
    series: ReadonlyArray<Series | ResolvedSeries>,
    theme: ChartTheme,
    deltaFormatter: (delta: number) => string
): LegendItem[] {
    const byKey = new Map(series.map((s) => [s.key, s]))
    return legendItemsFromSeries(series, theme)
        .map((item) => ({
            ...item,
            secondaryLabel: deltaFormatter(slopeDelta(byKey.get(item.key)!)),
        }))
        .sort((a, b) => slopeEnd(byKey.get(b.key)!) - slopeEnd(byKey.get(a.key)!))
}
