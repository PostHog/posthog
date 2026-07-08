import type { ChannelSemantics, FormatSpec } from 'flint-chart/core'

import { dayjs } from 'lib/dayjs'

const isDiscrete = (type: string | undefined): boolean => type === 'nominal' || type === 'ordinal'

/** Extract unique category values for a field, preserving data order, then
 *  applying the canonical ordinal sort when the semantics provide one.
 *  (Port of the equivalent helper in flint-chart's Chart.js backend.) */
export function extractCategories(
    data: Record<string, unknown>[],
    field: string,
    ordinalSortOrder?: string[]
): string[] {
    const seen = new Set<string>()
    const result: string[] = []
    for (const row of data) {
        const val = row[field]
        if (val != null) {
            const key = String(val)
            if (!seen.has(key)) {
                seen.add(key)
                result.push(key)
            }
        }
    }
    if (ordinalSortOrder && ordinalSortOrder.length > 0) {
        const orderMap = new Map(ordinalSortOrder.map((v, i) => [v, i]))
        result.sort((a, b) => {
            const ia = orderMap.get(a)
            const ib = orderMap.get(b)
            if (ia !== undefined && ib !== undefined) {
                return ia - ib
            }
            if (ia !== undefined) {
                return -1
            }
            if (ib !== undefined) {
                return 1
            }
            return 0
        })
    }
    return result
}

export function groupBy(data: Record<string, unknown>[], field: string): Map<string, Record<string, unknown>[]> {
    const groups = new Map<string, Record<string, unknown>[]>()
    for (const row of data) {
        const key = String(row[field] ?? '')
        let bucket = groups.get(key)
        if (!bucket) {
            bucket = []
            groups.set(key, bucket)
        }
        bucket.push(row)
    }
    return groups
}

/** Build a category-aligned value array for one series. Quill's `Series.data`
 *  is a plain `number[]` parallel to `labels`, so categories a series has no
 *  row for become 0. Duplicate rows for one category are summed. */
export function buildCategoryAlignedData(
    rows: Record<string, unknown>[],
    catField: string,
    valField: string,
    categories: string[]
): number[] {
    const byCategory = new Map<string, number>()
    for (const row of rows) {
        const cat = String(row[catField] ?? '')
        const val = Number(row[valField])
        if (Number.isFinite(val)) {
            byCategory.set(cat, (byCategory.get(cat) ?? 0) + val)
        }
    }
    return categories.map((c) => byCategory.get(c) ?? 0)
}

/** Detect which positional axis carries the discrete categories and which the measure. */
export function detectAxes(channelSemantics: Record<string, ChannelSemantics>): {
    categoryAxis: 'x' | 'y'
    valueAxis: 'x' | 'y'
} {
    if (channelSemantics.x && isDiscrete(channelSemantics.x.type)) {
        return { categoryAxis: 'x', valueAxis: 'y' }
    }
    if (channelSemantics.y && isDiscrete(channelSemantics.y.type)) {
        return { categoryAxis: 'y', valueAxis: 'x' }
    }
    return { categoryAxis: 'x', valueAxis: 'y' }
}

/** Turn Flint's semantic FormatSpec into a quill tick formatter. Intentionally
 *  partial: prefix/suffix/abbreviation and percent patterns cover the semantic
 *  types agents actually hit; full d3-format pattern support is a follow-up. */
export function makeTickFormatter(format?: FormatSpec): ((value: number) => string) | undefined {
    if (!format) {
        return undefined
    }
    const { pattern, prefix = '', suffix = '', abbreviate } = format
    const isPercentPattern = !!pattern && pattern.includes('%')
    return (value: number): string => {
        let v = value
        let percentSuffix = ''
        if (isPercentPattern) {
            // d3 percent patterns (".1%") multiply by 100 and append the sign
            v = value * 100
            percentSuffix = '%'
        }
        let body: string
        if (abbreviate && Math.abs(v) >= 1000) {
            body = Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(v)
        } else {
            body = Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(v)
        }
        return `${prefix}${body}${percentSuffix}${suffix}`
    }
}

/** d3 strftime tokens → dayjs format tokens, for the subset Flint's semantic
 *  layer emits via `ChannelSemantics.temporalFormat`. */
const STRFTIME_TO_DAYJS: Record<string, string> = {
    '%Y': 'YYYY',
    '%y': 'YY',
    '%m': 'MM',
    '%b': 'MMM',
    '%B': 'MMMM',
    '%d': 'D',
    '%e': 'D',
    '%a': 'ddd',
    '%A': 'dddd',
    '%H': 'HH',
    '%I': 'hh',
    '%M': 'mm',
    '%S': 'ss',
    '%p': 'A',
    '%j': 'DDD',
    '%q': 'Q',
}

export function strftimeToDayjsFormat(pattern: string): string {
    return pattern.replace(/%[a-zA-Z]/g, (token) => STRFTIME_TO_DAYJS[token] ?? token)
}

/** Format one temporal value (Date, ISO string, or epoch ms/s) as an axis label. */
export function formatTemporalLabel(raw: unknown, temporalFormat?: string): string {
    if (raw == null) {
        return ''
    }
    let d
    if (typeof raw === 'number' && Number.isFinite(raw)) {
        // Values below ~1e12 read as Unix seconds (same heuristic as the Chart.js backend)
        d = dayjs(raw < 1e12 ? raw * 1000 : raw)
    } else {
        d = dayjs(raw as string | Date)
    }
    if (!d.isValid()) {
        return String(raw)
    }
    return d.format(temporalFormat ? strftimeToDayjsFormat(temporalFormat) : 'MMM D, YYYY')
}

/** Millisecond timestamp for sorting temporal rows; NaN when unparseable. */
export function temporalSortValue(raw: unknown): number {
    if (raw == null) {
        return NaN
    }
    if (typeof raw === 'number' && Number.isFinite(raw)) {
        return raw < 1e12 ? raw * 1000 : raw
    }
    if (raw instanceof Date) {
        return raw.getTime()
    }
    const t = new Date(String(raw)).getTime()
    return Number.isFinite(t) ? t : NaN
}
