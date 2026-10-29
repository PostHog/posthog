import type { ChartTheme, ResolvedSeries, Series } from '../../core/types'
import type { LegendItem, LegendValue } from './Legend'

export function legendItemsFromSeries(
    series: ReadonlyArray<Series | ResolvedSeries>,
    theme: ChartTheme,
    values?: readonly LegendValue[]
): LegendItem[] {
    const palette = theme.colors
    const items: LegendItem[] = []
    for (let i = 0; i < series.length; i++) {
        const s = series[i]
        if (s.visibility?.excluded) {
            continue
        }
        const fallback = palette.length > 0 ? palette[i % palette.length] : '#000'
        const item: LegendItem = { key: s.key, label: s.label, color: s.color || fallback }
        if (values?.length) {
            item.values = computeLegendValues(s.data, values)
        }
        items.push(item)
    }
    return items
}

/** Fills value-column summaries into legend rows built elsewhere (a chart's own items), matching
 *  each row to its series by key. Rows that already carry values keep them. */
export function withLegendValues(
    items: LegendItem[],
    series: ReadonlyArray<Series | ResolvedSeries>,
    values: readonly LegendValue[] | undefined
): LegendItem[] {
    if (!values?.length) {
        return items
    }
    const dataByKey = new Map(series.map((s) => [s.key, s.data]))
    return items.map((item) =>
        item.values ? item : { ...item, values: computeLegendValues(dataByKey.get(item.key), values) }
    )
}

/** Summaries of a series' finite values, `null` for a series without any. */
export function computeLegendValues(
    data: readonly number[] | null | undefined,
    values: readonly LegendValue[]
): Partial<Record<LegendValue, number | null>> {
    let count = 0
    let sum = 0
    let min = Infinity
    let max = -Infinity
    let first: number | null = null
    let last: number | null = null
    for (const v of data ?? []) {
        if (v == null || !isFinite(v)) {
            continue
        }
        count++
        sum += v
        min = Math.min(min, v)
        max = Math.max(max, v)
        first ??= v
        last = v
    }
    const all: Record<LegendValue, number | null> =
        count === 0
            ? { mean: null, min: null, max: null, first: null, last: null, sum: null }
            : { mean: sum / count, min, max, first, last, sum }
    return Object.fromEntries(values.map((v) => [v, all[v]]))
}
