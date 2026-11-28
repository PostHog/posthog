import type { z } from 'zod'

import type { CdpRole } from '../cards'
import type { MetricSample } from './measurements'

export const SCRAPE_GAP_MS = 15_000

const P99 = 0.99

const iso = (at: number): string => new Date(at).toISOString()

export const WORKER_OF = {
    hogflow: 'cdp-cyclotron-worker-hogflow',
    email: 'cdp-cyclotron-worker-email',
} as const satisfies Record<string, z.infer<typeof CdpRole>>

export type Buckets = Record<string, number>

function add(
    into: Record<string, Buckets>,
    lateness: MetricSample['lateness'],
    before: MetricSample['lateness']
): void {
    for (const [queue, buckets] of Object.entries(lateness)) {
        const sum = (into[queue] ??= {})
        for (const [le, count] of Object.entries(buckets)) {
            sum[le] = (sum[le] ?? 0) + count - (before[queue]?.[le] ?? 0)
        }
    }
}

export function pickupsBetween(
    samples: readonly MetricSample[],
    roles: readonly string[],
    { from, to }: { from: number; to: number }
): { picked: Record<string, Buckets> } | { unread: string } {
    const picked: Record<string, Buckets> = {}
    const unscraped = roles.find((role) => !samples.some((sample) => sample.role === role))
    if (unscraped) {
        return { unread: `no metrics from ${unscraped}` }
    }
    const workers = samples.filter(({ role }) => roles.includes(role))
    for (const [worker, series] of Map.groupBy(workers, ({ role, replica }) => `${role}-${replica}`)) {
        const sorted = [...series].sort((a, b) => a.at - b.at)
        const first = sorted.findLastIndex(({ at }) => at <= from)
        const inside = sorted.slice(Math.max(first, 0)).filter(({ at }) => at <= to)
        const bounds = [...inside.map(({ at }) => at), to]
        const gap = bounds.findIndex((at, i) => i > 0 && at - bounds[i - 1] > SCRAPE_GAP_MS)
        if (first < 0 || gap > 0) {
            return { unread: `no metrics from ${worker} after ${iso(first < 0 ? from : bounds[gap - 1])}` }
        }
        // A scrape interval that straddles the step's end counts in both steps, so late pickups at a step's tail
        // never pass into the next step's larger volume unjudged.
        const last = inside.at(-1)!
        const next = sorted.find(({ at }) => at > to)
        const covered = last.at < to && next && next.at - last.at <= SCRAPE_GAP_MS ? [...inside, next] : inside
        covered.slice(1).forEach((sample, i) => {
            const previous = covered[i]
            add(picked, sample.lateness, sample.startedAt === previous.startedAt ? previous.lateness : {})
        })
    }
    return { picked }
}

export function p99Of(buckets: Buckets): { value: number; beyond: boolean } {
    const total = buckets['+Inf'] ?? 0
    const bounds = Object.keys(buckets)
        .filter((le) => le !== '+Inf')
        .map(Number)
        .sort((a, b) => a - b)
    const within = bounds.find((le) => (buckets[String(le)] ?? 0) >= P99 * total)
    return within === undefined ? { value: bounds.at(-1) ?? 0, beyond: true } : { value: within, beyond: false }
}
