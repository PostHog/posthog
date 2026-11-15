import { z } from 'zod'

import type { CdpRole, Named, Step } from '../cards'
import type { Definition } from '../cards/definitions'
import type { JournalEntry } from './judge'
import type { DriveWindow, MetricSample } from './measurements'

export type CpuPoint = { at: number; percent: number }

export type BarEvidence = {
    journal: readonly JournalEntry[]
    samples: readonly MetricSample[]
    drive: DriveWindow
    steps: Step[]
    writerCpu: CpuPoint[] | { unread: string }
}

export type BreakingPoint = { scale: number; at: string; offeredPerSecond: number; key?: string; value: number }

export type BarResult = {
    name: string
    unit: string
    passed: boolean
    unjudged?: string
    breakingPoint?: BreakingPoint
}

type Window = { from: number; to: number; last: boolean }

type Reading = { key?: string; value: number; passed: boolean } | { unread: string }

type BarDefinition = Definition & {
    unit: string
    read(evidence: BarEvidence, window: Window, params: unknown): Reading
}

const P99 = 0.99
const MINUTE_MS = 60_000
const SCRAPE_GAP_MS = 15_000

const WriterCpuParams = z.object({ percent: z.number().positive().max(100) }).strict()
const Queue = z.enum(['hogflow', 'email'])
const PickupParams = z.object({ seconds: z.number().positive(), queues: z.array(Queue).min(1) }).strict()

const WORKER_OF = {
    hogflow: 'cdp-cyclotron-worker-hogflow',
    email: 'cdp-cyclotron-worker-email',
} as const satisfies Record<z.infer<typeof Queue>, z.infer<typeof CdpRole>>

const iso = (at: number): string => new Date(at).toISOString()

const writerCpuUnder: BarDefinition = {
    name: 'writer_cpu_under',
    params: WriterCpuParams,
    unit: '%',
    read: ({ writerCpu }, { from, to }, params) => {
        if ('unread' in writerCpu) {
            return writerCpu
        }
        const { percent } = WriterCpuParams.parse(params)
        const minutes: number[] = []
        for (let minute = Math.ceil(from / MINUTE_MS) * MINUTE_MS; minute + MINUTE_MS <= to; minute += MINUTE_MS) {
            minutes.push(minute)
        }
        if (minutes.length === 0) {
            return { unread: 'no whole writer CPU minute' }
        }
        const readings = minutes.map((minute) => writerCpu.find(({ at }) => at === minute))
        const missing = readings.findIndex((reading) => reading === undefined)
        if (missing >= 0) {
            return { unread: `no writer CPU reading for the minute at ${iso(minutes[missing])}` }
        }
        const value = Math.max(...readings.map((reading) => reading!.percent))
        return { value, passed: value < percent }
    },
}

type Buckets = Record<string, number>

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

function pickupsBetween(
    samples: readonly MetricSample[],
    roles: readonly string[],
    { from, to }: Pick<Window, 'from' | 'to'>
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
        const covered = sorted.slice(Math.max(first, 0)).filter(({ at }) => at <= to)
        const bounds = [...covered.map(({ at }) => at), to]
        const gap = bounds.findIndex((at, i) => i > 0 && at - bounds[i - 1] > SCRAPE_GAP_MS)
        if (first < 0 || gap > 0) {
            return { unread: `no metrics from ${worker} after ${iso(first < 0 ? from : bounds[gap - 1])}` }
        }
        covered.slice(1).forEach((sample, i) => {
            const previous = covered[i]
            add(picked, sample.lateness, sample.startedAt === previous.startedAt ? previous.lateness : {})
        })
    }
    return { picked }
}

function p99Of(buckets: Buckets): number {
    const total = buckets['+Inf'] ?? 0
    const bounds = Object.keys(buckets)
        .filter((le) => le !== '+Inf')
        .map(Number)
        .sort((a, b) => a - b)
    return bounds.find((le) => (buckets[String(le)] ?? 0) >= P99 * total) ?? bounds.at(-1) ?? 0
}

const pickupP99Under: BarDefinition = {
    name: 'pickup_p99_under',
    params: PickupParams,
    unit: 's',
    read: ({ samples }, { from, to, last }, params) => {
        const { seconds, queues } = PickupParams.parse(params)
        const until = last ? Math.max(to, ...samples.map(({ at }) => at)) : to
        const pickups = pickupsBetween(
            samples,
            queues.map((queue) => WORKER_OF[queue]),
            { from, to: until }
        )
        if ('unread' in pickups) {
            return pickups
        }
        const { picked } = pickups
        const [worst] = queues
            .map((queue) => {
                const buckets = picked[queue] ?? {}
                const value = (buckets['+Inf'] ?? 0) > 0 ? p99Of(buckets) : (until - from) / 1000
                return { key: queue, value }
            })
            .sort((a, b) => b.value - a.value)
        return { ...worst, passed: worst.value <= seconds }
    },
}

export const BARS: BarDefinition[] = [writerCpuUnder, pickupP99Under]

const offeredPerSecond = (journal: readonly JournalEntry[], { from, to }: Window): number =>
    journal.filter(
        ({ kind, answer, offeredAt }) => (kind !== 'event' || answer.accepted) && offeredAt >= from && offeredAt < to
    ).length /
    ((to - from) / 1000)

export function judgeBars(bars: Named[], evidence: BarEvidence): BarResult[] {
    return bars.map(({ name, params }) => {
        const definition = BARS.find((bar) => bar.name === name)!
        const result = { name, unit: definition.unit }
        for (const [i, { scale, fromMs, toMs }] of evidence.steps.entries()) {
            const window = {
                from: evidence.drive.startedAt + fromMs,
                to: Math.min(evidence.drive.startedAt + toMs, evidence.drive.endedAt),
                last: i === evidence.steps.length - 1,
            }
            if (window.to <= window.from) {
                return { ...result, passed: false, unjudged: `the drive ended before the ${scale}x step` }
            }
            const reading = definition.read(evidence, window, params)
            if ('unread' in reading) {
                return { ...result, passed: false, unjudged: `${reading.unread} in the ${scale}x step` }
            }
            if (!reading.passed) {
                const { key, value } = reading
                const at = iso(window.from)
                const offered = offeredPerSecond(evidence.journal, window)
                return {
                    ...result,
                    passed: false,
                    breakingPoint: { scale, at, offeredPerSecond: offered, ...(key && { key }), value },
                }
            }
        }
        return { ...result, passed: true }
    })
}
