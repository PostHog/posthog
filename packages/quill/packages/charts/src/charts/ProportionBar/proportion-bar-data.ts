import type { LegendItem } from '../../components/Legend/Legend'
import { legendItemsFromSeries } from '../../components/Legend/legendItemsFromSeries'
import type { ChartTheme, Series } from '../../core/types'
import { percentage } from '../../utils/format'

/** The size of one part: the sum of its finite values, floored at 0. This matches how `PieChart`
 *  sizes a slice, so the same `series` gives the same shares in both charts. */
export function partValue(series: Series): number {
    let sum = 0
    for (const value of series.data) {
        if (Number.isFinite(value)) {
            sum += value
        }
    }
    return Math.max(0, sum)
}

/** Legend rows for a proportion bar. Each row carries `share · value` as its `secondaryLabel`,
 *  because the bar has no axis to read a size from. A row hidden through the legend keeps its
 *  place but shows no share, and its value leaves the total, so the rows agree with the bar. */
export function proportionLegendItems(
    series: Series[],
    theme: ChartTheme,
    valueFormatter: (value: number) => string,
    hiddenKeys: readonly string[] = []
): LegendItem[] {
    const hidden = new Set(hiddenKeys)
    const valueByKey = new Map(series.map((s) => [s.key, partValue(s)]))
    const total = series.reduce(
        (acc, s) => (s.visibility?.excluded || hidden.has(s.key) ? acc : acc + (valueByKey.get(s.key) ?? 0)),
        0
    )
    return legendItemsFromSeries(series, theme).map((item) => {
        if (hidden.has(item.key)) {
            return item
        }
        const value = valueByKey.get(item.key) ?? 0
        const share = total > 0 ? value / total : 0
        return { ...item, secondaryLabel: `${percentage(share, 1)} · ${valueFormatter(value)}` }
    })
}
