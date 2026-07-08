import type { ChartEncoding } from 'flint-chart/core'

/**
 * Opt-in aggregation transform, reimplementing the contract of flint-chart's
 * internal `applyAggregation` (not exported from `flint-chart/core`):
 *
 * - Rows group by every channel that has a `field` and no `aggregate`.
 * - Each aggregated channel yields a derived column `${field}_${op}`
 *   (`count` yields `_count`) — the names `resolveChannelSemantics` rewrites
 *   `ChannelSemantics.field` to, so templates pick them up automatically.
 * - When every derived column already exists, the caller pre-aggregated and
 *   the data passes through untouched.
 */
export function applyAggregation(
    encodings: Record<string, ChartEncoding>,
    data: Record<string, unknown>[]
): Record<string, unknown>[] {
    if (!data || data.length === 0) {
        return data
    }

    const specs: { field?: string; op: string; target: string }[] = []
    for (const enc of Object.values(encodings)) {
        if (!enc?.aggregate) {
            continue
        }
        if (enc.aggregate !== 'count' && !enc.field) {
            continue
        }
        specs.push({
            field: enc.field,
            op: enc.aggregate,
            target: enc.aggregate === 'count' ? '_count' : `${enc.field}_${enc.aggregate}`,
        })
    }
    if (specs.length === 0) {
        return data
    }
    if (specs.every((s) => Object.prototype.hasOwnProperty.call(data[0], s.target))) {
        return data
    }

    const groupFields: string[] = []
    const seen = new Set<string>()
    for (const enc of Object.values(encodings)) {
        if (!enc || enc.aggregate || !enc.field || seen.has(enc.field)) {
            continue
        }
        seen.add(enc.field)
        groupFields.push(enc.field)
    }

    const groups = new Map<string, Record<string, unknown>[]>()
    for (const row of data) {
        const key = JSON.stringify(groupFields.map((f) => row[f] ?? null))
        let bucket = groups.get(key)
        if (!bucket) {
            bucket = []
            groups.set(key, bucket)
        }
        bucket.push(row)
    }

    const reduceOp = (rows: Record<string, unknown>[], spec: { field?: string; op: string }): number => {
        if (spec.op === 'count') {
            return rows.length
        }
        const nums = rows.map((r) => Number(r[spec.field as string])).filter((v) => Number.isFinite(v))
        if (nums.length === 0) {
            return 0
        }
        const sum = nums.reduce((a, b) => a + b, 0)
        return spec.op === 'sum' ? sum : sum / nums.length
    }

    const out: Record<string, unknown>[] = []
    for (const rows of groups.values()) {
        const aggregated: Record<string, unknown> = {}
        for (const f of groupFields) {
            aggregated[f] = rows[0][f]
        }
        for (const spec of specs) {
            const val = reduceOp(rows, spec)
            aggregated[spec.target] = val
            // Keep the source column populated so semantic/format inference for
            // the measure channel still sees representative numeric values
            if (spec.op !== 'count' && spec.field) {
                aggregated[spec.field] = val
            }
        }
        out.push(aggregated)
    }
    return out
}
