import { z } from 'zod'

import type { Named, Step } from '../cards'
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

type Window = { from: number; to: number }

type Reading = { key?: string; value: number; passed: boolean } | { unread: string }

type BarDefinition = Definition & {
    unit: string
    read(evidence: BarEvidence, window: Window, params: unknown): Reading
}

const P99 = 0.99

const WriterCpuParams = z.object({ percent: z.number().positive().max(100) }).strict()
const PickupParams = z.object({ seconds: z.number().positive() }).strict()

const writerCpuUnder: BarDefinition = {
    name: 'writer_cpu_under',
    params: WriterCpuParams,
    unit: '%',
    read: ({ writerCpu }, { from, to }, params) => {
        if ('unread' in writerCpu) {
            return writerCpu
        }
        const { percent } = WriterCpuParams.parse(params)
        const inside = writerCpu.filter(({ at }) => at >= from && at < to).map((point) => point.percent)
        if (inside.length === 0) {
            return { unread: 'no writer CPU minute' }
        }
        const value = Math.max(...inside)
        return { value, passed: value < percent }
    },
}

type Buckets = Record<string, Record<string, number>>

function pickupsBetween(samples: readonly MetricSample[], { from, to }: Window): Buckets {
    const picked: Buckets = {}
    const byReplica = Map.groupBy(samples, ({ role, replica }) => `${role}/${replica}`)
    for (const series of byReplica.values()) {
        const sorted = [...series].sort((a, b) => a.at - b.at)
        const end = sorted.findLast(({ at }) => at <= to)
        if (end === undefined) {
            continue
        }
        const start = sorted.findLast(({ at }) => at <= from)
        // A replica that restarted inside the step counts from zero again.
        const before = start?.startedAt === end.startedAt ? start.lateness : {}
        for (const [queue, buckets] of Object.entries(end.lateness)) {
            const into = (picked[queue] ??= {})
            for (const [le, count] of Object.entries(buckets)) {
                into[le] = (into[le] ?? 0) + count - (before[queue]?.[le] ?? 0)
            }
        }
    }
    return picked
}

function p99Of(buckets: Record<string, number>): number | undefined {
    const total = buckets['+Inf'] ?? 0
    if (total === 0) {
        return undefined
    }
    const bound = Object.keys(buckets)
        .filter((le) => le !== '+Inf')
        .map(Number)
        .sort((a, b) => a - b)
        .find((le) => (buckets[String(le)] ?? 0) >= P99 * total)
    return bound ?? Number.POSITIVE_INFINITY
}

const pickupP99Under: BarDefinition = {
    name: 'pickup_p99_under',
    params: PickupParams,
    unit: 's',
    read: ({ samples }, window, params) => {
        const { seconds } = PickupParams.parse(params)
        const worst = Object.entries(pickupsBetween(samples, window))
            .flatMap(([queue, buckets]) => {
                const p99 = p99Of(buckets)
                return p99 === undefined ? [] : [{ key: queue, value: p99 }]
            })
            .sort((a, b) => b.value - a.value)[0]
        return worst === undefined ? { unread: 'no job pickup' } : { ...worst, passed: worst.value <= seconds }
    },
}

export const BARS: BarDefinition[] = [writerCpuUnder, pickupP99Under]

const offeredPerSecond = (journal: readonly JournalEntry[], { from, to }: Window): number =>
    journal.filter(({ offeredAt, answer }) => answer.accepted && offeredAt >= from && offeredAt < to).length /
    ((to - from) / 1000)

export function judgeBars(bars: Named[], evidence: BarEvidence): BarResult[] {
    return bars.map(({ name, params }) => {
        const definition = BARS.find((bar) => bar.name === name)!
        const result = { name, unit: definition.unit }
        for (const { scale, fromMs, toMs } of evidence.steps) {
            const window = {
                from: evidence.drive.startedAt + fromMs,
                to: Math.min(evidence.drive.startedAt + toMs, evidence.drive.endedAt),
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
                const at = new Date(window.from).toISOString()
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
