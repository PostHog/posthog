import { z } from 'zod'

import type { CdpRole, Named, Step } from '../cards'
import type { Definition } from '../cards/definitions'
import type { JournalEntry } from './judge'
import {
    type DriveWindow,
    type HostSample,
    type MetricSample,
    SCRAPE_GAP_MS,
    stepHostBusyShareOf,
} from './measurements'

export type CpuPoint = { at: number; percent: number }

export type BarEvidence = {
    journal: readonly JournalEntry[]
    samples: readonly MetricSample[]
    drive: DriveWindow
    steps: readonly (Step & { offeredUnits?: number })[]
    writerCpu: WriterCpu
    host: readonly HostSample[]
    hostCpuCeiling?: number
    settled?: ReadonlyMap<number, readonly BarResult[]>
}

export type WriterCpu = CpuPoint[] | { unread: string } | { unsourced: string }

export type StepPoint = { scale: number; at: string; offeredPerSecond: number }

export type BreakingPoint = StepPoint & { key?: string; value: number; part: string }

export type HarnessLimit = { scale: number; by: 'run_host' }

type Read = { key?: string; value: number; part: string }

export type BarResult = {
    name: string
    unit: string
    limit: number
    passed: boolean
    unjudged?: string
    harnessLimit?: HarnessLimit
    breakingPoint?: BreakingPoint
    reading?: Read
}

export type StepReading = Pick<BarResult, 'name' | 'unit' | 'limit'> &
    ({ value: number; key?: string; part: string; passed: boolean } | { value: null; passed: null; unjudged: string })

type Window = { from: number; to: number; last: boolean; idle?: boolean }

type Reading =
    | { key?: string; value: number; passed: boolean; part: string }
    | { unread: string }
    | { unsourced: string }

type BarDefinition = Definition & {
    limit(params: unknown): number
    unit: string
    read(evidence: BarEvidence, window: Window, params: unknown): Reading
}

const P99 = 0.99
const MINUTE_MS = 60_000

const WriterCpuParams = z.object({ percent: z.number().positive().max(100) }).strict()
const Queue = z.enum(['hogflow', 'email'])
const PickupParams = z.object({ seconds: z.number().positive(), queues: z.array(Queue).min(1) }).strict()

const CYCLOTRON_WRITER = 'db:cyclotron'

const WORKER_OF = {
    hogflow: 'cdp-cyclotron-worker-hogflow',
    email: 'cdp-cyclotron-worker-email',
} as const satisfies Record<z.infer<typeof Queue>, z.infer<typeof CdpRole>>

const iso = (at: number): string => new Date(at).toISOString()

const percent = (share: number): string => `${Number((share * 100).toFixed(1))}%`

const writerCpuUnder: BarDefinition = {
    name: 'writer_cpu_under',
    params: WriterCpuParams,
    limit: (params) => WriterCpuParams.parse(params).percent,
    unit: '%',
    read: ({ writerCpu }, { from, to }, params) => {
        if (!Array.isArray(writerCpu)) {
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
        const readings = minutes.map((minute) =>
            writerCpu.find(({ at, percent }) => at === minute && Number.isFinite(percent))
        )
        const missing = readings.findIndex((reading) => reading === undefined)
        if (missing >= 0) {
            return { unread: `no writer CPU reading for the minute at ${iso(minutes[missing])}` }
        }
        const value = Math.max(...readings.map((reading) => reading!.percent))
        return { value, passed: value < percent, part: CYCLOTRON_WRITER }
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

function p99Of(buckets: Buckets): { value: number; beyond: boolean } {
    const total = buckets['+Inf'] ?? 0
    const bounds = Object.keys(buckets)
        .filter((le) => le !== '+Inf')
        .map(Number)
        .sort((a, b) => a - b)
    const within = bounds.find((le) => (buckets[String(le)] ?? 0) >= P99 * total)
    return within === undefined ? { value: bounds.at(-1) ?? 0, beyond: true } : { value: within, beyond: false }
}

const pickupP99Under: BarDefinition = {
    name: 'pickup_p99_under',
    params: PickupParams,
    limit: (params) => PickupParams.parse(params).seconds,
    unit: 's',
    read: ({ samples }, { from, to, last, idle }, params) => {
        const { seconds, queues } = PickupParams.parse(params)
        const until = last ? samples.reduce((latest, { at }) => Math.max(latest, at), to) : to
        const pickups = pickupsBetween(
            samples,
            queues.map((queue) => WORKER_OF[queue]),
            { from, to: until }
        )
        if ('unread' in pickups) {
            return pickups
        }
        const readings = queues
            .map((queue) => {
                const buckets = pickups.picked[queue] ?? {}
                const { value, beyond } =
                    (buckets['+Inf'] ?? 0) > 0
                        ? p99Of(buckets)
                        : { value: idle ? 0 : (until - from) / 1000, beyond: false }
                return {
                    key: queue,
                    value,
                    passed: beyond ? undefined : value <= seconds,
                    part: `role:${WORKER_OF[queue]}`,
                }
            })
            .sort((a, b) => b.value - a.value)
        const broken = readings.find(
            ({ passed, value }) => passed === false || (passed === undefined && value >= seconds)
        )
        const unknown = readings.find(({ passed }) => passed === undefined)
        if (broken) {
            return { ...broken, passed: false }
        }
        if (unknown) {
            return { unread: `the ${unknown.key} p99 is past the histogram's largest bucket of ${unknown.value} s` }
        }
        return { ...readings[0], passed: true }
    },
}

export const BARS: BarDefinition[] = [writerCpuUnder, pickupP99Under]

export const offeredPerSecond = (journal: readonly JournalEntry[], { from, to }: Pick<Window, 'from' | 'to'>): number =>
    journal.filter(
        ({ kind, answer, offeredAt }) => (kind !== 'event' || answer.accepted) && offeredAt >= from && offeredAt < to
    ).length /
    ((to - from) / 1000)

function hostOverCeiling({ host, hostCpuCeiling }: BarEvidence, window: Window, scale: number): string | undefined {
    if (hostCpuCeiling === undefined) {
        return undefined
    }
    const share = stepHostBusyShareOf(host, window)
    if (share === undefined) {
        return `fewer than two host CPU samples in the ${scale}x step`
    }
    return share >= hostCpuCeiling
        ? `the run host was ${percent(share)} busy in the ${scale}x step, at or over the ${percent(hostCpuCeiling)} ceiling`
        : undefined
}

const windowOf = ({ drive, steps }: BarEvidence, i: number): Pick<Window, 'from' | 'to'> => ({
    from: drive.startedAt + steps[i].fromMs,
    to: Math.min(drive.startedAt + steps[i].toMs, drive.endedAt),
})

function offeredRateOf(evidence: BarEvidence, i: number): number {
    const window = windowOf(evidence, i)
    const { offeredUnits } = evidence.steps[i]
    if (window.to <= window.from) {
        return 0
    }
    return offeredUnits === undefined
        ? offeredPerSecond(evidence.journal, window)
        : offeredUnits / ((window.to - window.from) / 1000)
}

type StepVerdict = Pick<BarResult, 'unjudged' | 'harnessLimit' | 'breakingPoint'>

type StepJudgment = { verdict: StepVerdict; reading?: Read }

function judgeStepOf(
    definition: BarDefinition,
    params: unknown,
    evidence: BarEvidence,
    i: number,
    last: boolean
): StepJudgment {
    const { scale, offeredUnits } = evidence.steps[i]
    const window = { ...windowOf(evidence, i), last }
    const idle =
        offeredUnits !== undefined &&
        !evidence.journal.some(
            ({ answer, offeredAt }) => answer.accepted && offeredAt >= window.from && offeredAt < window.to
        )
    const point = (): StepPoint => ({ scale, at: iso(window.from), offeredPerSecond: offeredRateOf(evidence, i) })
    if (window.to <= window.from) {
        return { verdict: { unjudged: `the drive ended before the ${scale}x step` } }
    }
    const overloaded = hostOverCeiling(evidence, window, scale)
    if (overloaded !== undefined) {
        return { verdict: { unjudged: overloaded, harnessLimit: { scale, by: 'run_host' } } }
    }
    const reading = definition.read(evidence, { ...window, idle }, params)
    if ('unsourced' in reading) {
        return { verdict: { unjudged: reading.unsourced } }
    }
    if ('unread' in reading) {
        return {
            verdict: { unjudged: `${reading.unread} in the ${scale}x step`, harnessLimit: { scale, by: 'run_host' } },
        }
    }
    const { key, value, part, passed } = reading
    const read = { ...(key && { key }), value, part }
    return { verdict: passed ? {} : { breakingPoint: { ...point(), ...read } }, reading: read }
}

function settledStepOf(
    definition: BarDefinition,
    params: unknown,
    evidence: BarEvidence,
    i: number,
    name: string
): StepJudgment {
    const live = evidence.settled?.get(i)?.find((settled) => settled.name === name)
    if (live?.breakingPoint) {
        const { key, value, part } = live.breakingPoint
        return {
            verdict: { breakingPoint: { ...live.breakingPoint, offeredPerSecond: offeredRateOf(evidence, i) } },
            reading: { ...(key && { key }), value, part },
        }
    }
    const nominal = judgeStepOf(definition, params, evidence, i, i === evidence.steps.length - 1)
    if (nominal.verdict.breakingPoint || !live?.passed) {
        return nominal
    }
    return { verdict: {}, reading: nominal.reading ?? live.reading }
}

const definitionOf = (name: string): BarDefinition => BARS.find((bar) => bar.name === name)!

export const unsourced = ({ unjudged, harnessLimit }: BarResult): boolean =>
    unjudged !== undefined && harnessLimit === undefined

export function judgeStep(bars: Named[], evidence: BarEvidence, i: number): BarResult[] {
    return bars.map(({ name, params }) => {
        const definition = definitionOf(name)
        const { verdict, reading } = judgeStepOf(definition, params, evidence, i, false)
        return {
            name,
            unit: definition.unit,
            limit: definition.limit(params),
            passed: Object.keys(verdict).length === 0,
            ...verdict,
            ...(reading && { reading }),
        }
    })
}

export function stepReadingsOf(bars: Named[], evidence: BarEvidence): StepReading[][] {
    return evidence.steps.map((_step, i) =>
        bars.map(({ name, params }) => {
            const definition = definitionOf(name)
            const bar = { name, unit: definition.unit, limit: definition.limit(params) }
            const { verdict, reading } = settledStepOf(definition, params, evidence, i, name)
            return reading
                ? { ...bar, ...reading, passed: verdict.breakingPoint === undefined }
                : {
                      ...bar,
                      value: null,
                      passed: null,
                      unjudged: verdict.unjudged ?? 'the live judge kept no reading of the step',
                  }
        })
    )
}

export function judgeBars(bars: Named[], evidence: BarEvidence): BarResult[] {
    return bars.map(({ name, params }) => {
        const definition = definitionOf(name)
        const result = { name, unit: definition.unit, limit: definition.limit(params) }
        if (evidence.steps.length === 0) {
            return { ...result, passed: false, unjudged: 'the drive ended before its first step' }
        }
        for (let i = 0; i < evidence.steps.length; i++) {
            const { verdict } = settledStepOf(definition, params, evidence, i, name)
            if (Object.keys(verdict).length > 0) {
                return { ...result, passed: false, ...verdict }
            }
        }
        return { ...result, passed: true }
    })
}
