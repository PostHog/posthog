import { readFileSync } from 'fs'
import { setTimeout as sleep } from 'timers/promises'
import { z } from 'zod'

import { internalFetch } from '~/common/utils/request'

import type { CdpRole, Named, Step } from '../cards'
import type { Definition } from '../cards/definitions'
import type { ObservationName } from '../environment/failover'
import { ReplicaOf, nameOf } from '../environment/identity'
import type { QueueCounts, WriterBackends } from '../probe/cyclotron-probe'
import type { WriterSample } from '../probe/writer-probe'
import type { ValveTimelineEntry } from '../valves/valves'
import { CounterReading, counterDrift } from './drift'
import { deliveryKey } from './invariants'
import type { JudgeEvidence } from './invariants'
import { SCRAPE_GAP_MS, WORKER_OF } from './pickups'

export type MetricSample = {
    role: string
    replica: number
    at: number
    fetchedAt?: number
    startedAt: number
    cpuSeconds: number
    rssBytes: number
    processed: Record<string, number>
    pgClientErrors: number
    consumerLoopErrors: number
    janitorStalled: number
    lateness: Record<string, Record<string, number>>
}

export type MissedScrape = { role: string; replica: number; at: number }

export type HostSample = { at: number; busyTicks: number; totalTicks: number }

export type Sampled = { samples: MetricSample[]; missed: MissedScrape[]; host: HostSample[] }

export type QueueSample = { at: number } & (QueueCounts | { error: string })

export type ActivitySample = { at: number } & ({ backends: WriterBackends } | { error: string })

export function readActivity(
    read: () => Promise<WriterBackends>,
    now: () => number = Date.now
): Promise<ActivitySample> {
    const at = now()
    return read().then(
        (backends) => ({ at: now(), backends }),
        (error: unknown) => ({ at, error: error instanceof Error ? error.message : String(error) })
    )
}

export type Probed = { writer: WriterSample[]; queue: QueueSample[]; activity?: ActivitySample[] }

export type DriveWindow = { startedAt: number; endedAt: number; warmedAt?: number }

type Value = { value: number; censored?: true } | { value: null; censored: true }

type Measured = { key?: string; incomplete?: true; unmeasured?: string } & Value

export type Measurement = { name: string; unit: string } & Measured

export type MeasureEvidence = Omit<JudgeEvidence, 'janitorResets' | 'boundary'> &
    Readonly<Sampled> &
    Readonly<Probed> & {
        sampledFrom: number
        drive: DriveWindow
        steps: readonly Step[]
        timeline: readonly ValveTimelineEntry[]
        counters?: CounterReading
        truthFrom: number
        unread?: string
        horizonAt?: number
        converged?: boolean
        unsettled?: string
    }

export type MeasurementDefinition = Definition & {
    unit: string
    measure(evidence: MeasureEvidence): Measured[]
}

export const SAMPLE_INTERVAL_MS = 5000
export const SCRAPE_TIMEOUT_MS = 2000
const BASELINE_WITHIN_MS = 10_000
const BASELINE_RETRY_MS = 500

const byRole = (samples: readonly MetricSample[]): Map<string, MetricSample[]> =>
    Map.groupBy(
        [...samples].sort((a, b) => a.at - b.at),
        ({ role }) => role
    )

const completeness = (role: string, missed: readonly MissedScrape[]): { incomplete?: true } =>
    missed.some((miss) => miss.role === role) ? { incomplete: true } : {}

const lostCpu = (ofReplica: readonly MetricSample[], missed: readonly MissedScrape[]): boolean =>
    new Set(ofReplica.map(({ startedAt }) => startedAt)).size > 1 ||
    missed.some(
        (miss) =>
            miss.role === ofReplica[0].role && miss.replica === ofReplica[0].replica && miss.at > ofReplica.at(-1)!.at
    )

type Counter = (sample: MetricSample) => number

const increaseOf = (ofReplica: readonly MetricSample[], read: Counter, since: number): number =>
    [...Map.groupBy(ofReplica, ({ startedAt }) => startedAt)].reduce((sum, [startedAt, lifetime]) => {
        const startedWhileSampled = startedAt * 1000 >= since
        return sum + read(lifetime.at(-1)!) - (startedWhileSampled ? 0 : read(lifetime[0]))
    }, 0)

const increaseAcrossReplicas = (replicas: readonly MetricSample[][], read: Counter, since: number): number =>
    replicas.reduce((sum, ofReplica) => sum + increaseOf(ofReplica, read, since), 0)

const JANITOR: z.infer<typeof CdpRole> = 'cdp-cyclotron-v2-janitor'

export function janitorResetsOf({ samples, sampledFrom }: Pick<Sampled, 'samples'> & { sampledFrom: number }): number {
    const replicas = replicasOf(byRole(samples).get(JANITOR) ?? [])
    return increaseAcrossReplicas(replicas, ({ janitorStalled }) => janitorStalled, sampledFrom)
}

export const roleCpuSeconds: MeasurementDefinition = {
    name: 'role_cpu_seconds',
    params: z.object({}).strict(),
    unit: 's',
    measure: ({ samples, missed, sampledFrom }) =>
        [...byRole(samples)].map(([role, ofRole]) => {
            const replicas = replicasOf(ofRole)
            return {
                key: role,
                value: increaseAcrossReplicas(replicas, ({ cpuSeconds }) => cpuSeconds, sampledFrom),
                ...(replicas.some((ofReplica) => lostCpu(ofReplica, missed)) ? { incomplete: true as const } : {}),
            }
        }),
}

export const maxOf = (values: readonly number[]): number =>
    values.reduce((max, value) => Math.max(max, value), -Infinity)

export const roleRssMaxBytes: MeasurementDefinition = {
    name: 'role_rss_max_bytes',
    params: z.object({}).strict(),
    unit: 'bytes',
    measure: ({ samples, missed }) =>
        [...byRole(samples)].map(([role, ofRole]) => ({
            key: role,
            value: maxOf(ofRole.map(({ rssBytes }) => rssBytes)),
            ...completeness(role, missed),
        })),
}

const nearestRank = (sorted: number[], share: number): number => sorted[Math.ceil(share * sorted.length) - 1]

export const deliveryLatencyMs: MeasurementDefinition = {
    name: 'delivery_latency_ms',
    params: z.object({}).strict(),
    unit: 'ms',
    measure: ({ journal, truth }) => {
        const firstAccepted = new Map<string, number>()
        for (const { unitId, actionId, status, at } of [...truth].sort((a, b) => a.seq - b.seq)) {
            const key = unitId !== undefined && actionId !== undefined ? deliveryKey(unitId, actionId) : undefined
            if (key !== undefined && status >= 200 && status < 300 && !firstAccepted.has(key)) {
                firstAccepted.set(key, Date.parse(at))
            }
        }
        const latencies = journal
            .filter(({ answer }) => answer.accepted)
            .flatMap(({ unitId, offeredAt, expect }) =>
                expect.deliveries.flatMap((actionId) => {
                    const deliveredAt = firstAccepted.get(deliveryKey(unitId, actionId))
                    return deliveredAt === undefined ? [] : [deliveredAt - offeredAt]
                })
            )
            .sort((a, b) => a - b)
        return latencies.length === 0
            ? []
            : [
                  { key: 'p50', value: nearestRank(latencies, 0.5) },
                  { key: 'p95', value: nearestRank(latencies, 0.95) },
                  { key: 'max', value: latencies.at(-1)! },
              ]
    },
}

const terminationsOf = (
    timeline: readonly ValveTimelineEntry[]
): (ValveTimelineEntry & Required<Pick<ValveTimelineEntry, 'exit'>>)[] =>
    timeline.flatMap((entry) => (entry.exit === undefined ? [] : [{ ...entry, exit: entry.exit }]))

const unmeasured = (reason: string): Measured => ({ value: null, censored: true, unmeasured: reason })

export const roleExitMs: MeasurementDefinition = {
    name: 'role_exit_ms',
    params: z.object({}).strict(),
    unit: 'ms',
    measure: ({ timeline }) => {
        const terminations = terminationsOf(timeline)
        if (timeline.filter(({ valve }) => valve === 'role.terminate').length > 1) {
            return [unmeasured('the card terminates more than one role, so its exits have no stable key')]
        }
        return terminations.map(({ target, exit }) =>
            exit.exitedAt === undefined
                ? { key: 'sigterm', ...unmeasured(`${target} did not exit`) }
                : exit.signal === 'SIGKILL'
                  ? { key: 'sigterm', ...unmeasured('a SIGKILL exit is not measured in this release') }
                  : { key: 'sigterm', value: Date.parse(exit.exitedAt) - Date.parse(exit.signalledAt) }
        )
    },
}

export const leaseReclaimMs: MeasurementDefinition = {
    name: 'lease_reclaim_ms',
    params: z.object({}).strict(),
    unit: 'ms',
    measure: () => [unmeasured('not measured in this release')],
}

export const resentInvocations: MeasurementDefinition = {
    name: 'resent_invocations',
    params: z.object({}).strict(),
    unit: 'invocations',
    measure: () => [{ key: 'total', ...unmeasured('not measured: a run-scoped resend count is a follow-up') }],
}

export type Phase = { from: number; to: number }

export type Phases = { baseline: Phase; valve?: Phase; failback?: Phase }

const appliedDuring = (drive: DriveWindow, timeline: readonly ValveTimelineEntry[]): ValveTimelineEntry[] =>
    timeline.filter(({ intentAt }) => intentAt !== undefined && Date.parse(intentAt) < drive.endedAt)

export function phasesOf(drive: DriveWindow, timeline: readonly ValveTimelineEntry[]): Phases {
    const applied = appliedDuring(drive, timeline).map(({ intentAt, releaseIntentAt, releasedAt }) => {
        const released = releaseIntentAt ?? releasedAt
        return { intent: Date.parse(intentAt!), released: released === undefined ? Infinity : Date.parse(released) }
    })
    const from = Math.min(drive.warmedAt ?? drive.startedAt, drive.endedAt)
    if (applied.length === 0) {
        return { baseline: { from, to: drive.endedAt } }
    }
    const intent = Math.max(Math.min(...applied.map(({ intent }) => intent)), from)
    const released = Math.max(...applied.map(({ released }) => released))
    return {
        baseline: { from, to: intent },
        valve: { from: intent, to: Math.min(released, drive.endedAt) },
        ...(released < drive.endedAt ? { failback: { from: released, to: drive.endedAt } } : {}),
    }
}

export const MIN_BASELINE_SECONDS = 30

const within = ({ from, to }: Phase, at: number): boolean => from <= at && at < to

const lastBefore = <T extends { at: number }>(series: readonly T[], at: number): T | undefined =>
    series.filter((sample) => sample.at < at).at(-1)

const byTime = <T extends { at: number }>(series: readonly T[]): T[] => [...series].sort((a, b) => a.at - b.at)

const committedAt = ({ at, latencyMs }: WriterSample): number => at + latencyMs

function longestIdle(writer: readonly WriterSample[], from: number, to: number): number {
    let probedUntil = from
    let longest = 0
    for (const sample of byTime(writer)) {
        if (sample.at >= to || committedAt(sample) <= probedUntil) {
            continue
        }
        longest = Math.max(longest, sample.at - probedUntil)
        probedUntil = committedAt(sample)
    }
    return Math.max(longest, to - probedUntil)
}

type Outage = { from: number; to?: number }

function outagesOf(writer: readonly WriterSample[]): Outage[] {
    const outages: Outage[] = []
    let lastCommit: number | undefined
    let open: Outage | undefined
    for (const sample of byTime(writer)) {
        if (sample.ok) {
            if (open) {
                outages.push({ ...open, to: committedAt(sample) })
                open = undefined
            }
            lastCommit = committedAt(sample)
        } else {
            open ??= { from: lastCommit ?? sample.at }
        }
    }
    return open ? [...outages, open] : outages
}

const seconds = (ms: number): number => ms / 1000

function writerUnavailable(writer: readonly WriterSample[], phase: Phase): Measured[] {
    if (!writer.some(({ at }) => within(phase, at))) {
        return []
    }
    const overlapping = outagesOf(writer).filter(({ from, to }) => from < phase.to && (to ?? Infinity) > phase.from)
    const unavailable = overlapping.reduce(
        (sum, { from, to }) => sum + Math.min(to ?? Infinity, phase.to) - Math.max(from, phase.from),
        0
    )
    const censored = overlapping.some(({ to }) => (to ?? Infinity) > phase.to)
    return [{ value: seconds(unavailable), ...(censored ? { censored: true as const } : {}) }]
}

function firstCommitAfterFailure(writer: readonly WriterSample[], phase: Phase): Measured[] {
    const sorted = byTime(writer).filter((sample) => committedAt(sample) >= phase.from)
    const failed = sorted.find(({ ok, at }) => !ok && at < phase.to)
    if (failed === undefined) {
        return sorted.some(({ at }) => within(phase, at)) ? [{ value: 0 }] : []
    }
    const commit = sorted.find(({ ok, at }) => ok && at > failed.at)
    return commit !== undefined && committedAt(commit) <= phase.to
        ? [{ value: seconds(committedAt(commit) - phase.from) }]
        : [{ value: seconds(phase.to - phase.from), censored: true }]
}

const counted = (queue: readonly QueueSample[]): (QueueCounts & { at: number })[] =>
    byTime(queue).filter((sample): sample is QueueCounts & { at: number } => !('error' in sample))

const ENVELOPE_MS = 10 * 60_000
const DRAINED_FOR_MS = 60_000
const QUEUE_GAP_MS = 15_000

function readThroughout(queue: readonly QueueSample[], phase: Phase): boolean {
    const edges = [
        phase.from,
        ...counted(queue)
            .filter(({ at }) => within(phase, at))
            .map(({ at }) => at),
        phase.to,
    ]
    return edges.every((at, i) => i === 0 || at - edges[i - 1] <= QUEUE_GAP_MS)
}

function drain(queue: readonly QueueSample[], baseline: Phase, phase: Phase): Measured[] {
    const recent = { from: Math.max(baseline.from, baseline.to - ENVELOPE_MS), to: baseline.to }
    const envelope = counted(queue).filter(({ at }) => within(recent, at))
    const inPhase = byTime(queue).filter(({ at }) => within(phase, at))
    if (
        seconds(baseline.to - baseline.from) < MIN_BASELINE_SECONDS ||
        envelope.length === 0 ||
        !inPhase.some((sample) => !('error' in sample))
    ) {
        return []
    }
    const maxDue = Math.max(...envelope.map(({ due }) => due))
    const maxAge = Math.max(...envelope.map(({ oldestDueSeconds }) => oldestDueSeconds))
    const inside = (sample: QueueSample): boolean =>
        !('error' in sample) && sample.due <= maxDue && sample.oldestDueSeconds <= maxAge
    const left = inPhase.findIndex((sample) => !('error' in sample) && !inside(sample))
    if (left < 0) {
        return [{ value: 0, ...(readThroughout(queue, phase) ? {} : { incomplete: true as const }) }]
    }
    let insideSince: number | undefined
    let previous = inPhase[left].at
    for (const sample of inPhase.slice(left)) {
        const gapped = sample.at - previous > QUEUE_GAP_MS
        previous = sample.at
        insideSince = inside(sample) ? (gapped ? sample.at : (insideSince ?? sample.at)) : undefined
        if (insideSince !== undefined && sample.at - insideSince >= DRAINED_FOR_MS) {
            return [{ value: seconds(insideSince - phase.from) }]
        }
    }
    return [{ value: null, censored: true }]
}

const spanning = <T extends { at: number }>(series: readonly T[], phase: Phase): T[] => {
    const reference = lastBefore(series, phase.from)
    return [...(reference ? [reference] : []), ...series.filter(({ at }) => within(phase, at))]
}

const inside = <T extends { at: number }>(series: readonly T[], phase: Phase): T[] =>
    series.filter(({ at }) => within(phase, at))

type Opened<T> = { window: T[]; from: number; fromOpening: boolean; before: (read: (sample: T) => number) => number }

// Opening at the scrape before the baseline lets a quiet warm-up dilute the rate, so the counter is interpolated at the
// baseline's start. Across a restart nothing can be interpolated, so the rate opens at the first scrape after it.
function openedAt<T extends { at: number; startedAt?: number }>(series: readonly T[], phase: Phase): Opened<T> {
    const window = spanning(series, phase)
    const [reference, first] = window
    if (first === undefined || reference.at >= phase.from) {
        return { window, from: reference?.at ?? phase.from, fromOpening: false, before: () => 0 }
    }
    if (reference.startedAt !== first.startedAt) {
        return { window: window.slice(1), from: first.at, fromOpening: true, before: () => 0 }
    }
    const share = (phase.from - reference.at) / (first.at - reference.at)
    return { window, from: phase.from, fromOpening: true, before: (read) => (read(first) - read(reference)) * share }
}

// Start times are whole seconds, so the opening lifetime is told by identity, not by its start time.
const increaseFromOpening = (window: readonly MetricSample[], read: Counter): number =>
    [...Map.groupBy(window, ({ startedAt }) => startedAt)].reduce(
        (sum, [startedAt, lifetime]) =>
            sum + read(lifetime.at(-1)!) - (startedAt === window[0].startedAt ? read(lifetime[0]) : 0),
        0
    )

const openedSpanOf = ({ window, from }: Opened<{ at: number }>): number =>
    window.length < 2 ? 0 : window.at(-1)!.at - from

const bracketing = <T extends { at: number }>(series: readonly T[], phase: Phase): T[] => {
    const closing = series.find(({ at }) => at >= phase.to)
    return [...spanning(series, phase), ...(closing ? [closing] : [])]
}

const replicasOf = (samples: readonly MetricSample[]): MetricSample[][] => [
    ...Map.groupBy(byTime(samples), ({ role, replica }) => `${role}-${replica}`).values(),
]

function phaseIncrease(
    samples: readonly MetricSample[],
    missed: readonly MissedScrape[],
    read: Counter,
    phase: Phase
): Measured {
    let value = 0
    let incomplete = false
    for (const ofReplica of replicasOf(samples)) {
        const window = bracketing(ofReplica, phase)
        if (window.length === 0) {
            continue
        }
        const [first, last] = [window[0], window.at(-1)!]
        value += increaseOf(window, read, first.at)
        incomplete ||=
            first.at >= phase.from ||
            last.at < phase.to ||
            new Set(window.map(({ startedAt }) => startedAt)).size > 1 ||
            missed.some(
                (miss) =>
                    miss.role === first.role &&
                    miss.replica === first.replica &&
                    miss.at > first.at &&
                    miss.at < last.at
            )
    }
    return { value, ...(incomplete ? { incomplete: true as const } : {}) }
}

const spanOf = (window: readonly { at: number }[]): number => (window.length < 2 ? 0 : window.at(-1)!.at - window[0].at)

function phaseRate(samples: readonly MetricSample[], read: Counter, phase: Phase): number {
    return replicasOf(samples).reduce((sum, ofReplica) => {
        const opened = openedAt(ofReplica, phase)
        const span = openedSpanOf(opened)
        return span <= 0
            ? sum
            : sum +
                  ((opened.fromOpening
                      ? increaseFromOpening(opened.window, read)
                      : increaseOf(opened.window, read, opened.from)) -
                      opened.before(read)) /
                      seconds(span)
    }, 0)
}

const queuesOf = (samples: readonly MetricSample[]): string[] => [
    ...new Set(samples.flatMap(({ processed }) => Object.keys(processed))),
]

const claimRate = (samples: readonly MetricSample[], queue: string, phase: Phase): number =>
    phaseRate(samples, ({ processed }) => processed[queue] ?? 0, phase)

function scrapedSeconds(samples: readonly MetricSample[], phase: Phase): number {
    const spans = replicasOf(samples)
        .map((ofReplica) => openedAt(ofReplica, phase).window)
        .filter((window) => window.length > 0)
        .map((window) => seconds(spanOf(window)))
    return spans.length === 0 ? 0 : Math.min(...spans)
}

function busyShareOf(span: readonly HostSample[], before: Opened<HostSample>['before'] = () => 0): number | undefined {
    const [first, last] = [span.at(0), span.at(-1)]
    if (first === undefined || last === undefined) {
        return undefined
    }
    const total = last.totalTicks - first.totalTicks - before(({ totalTicks }) => totalTicks)
    return total > 0 ? (last.busyTicks - first.busyTicks - before(({ busyTicks }) => busyTicks)) / total : undefined
}

export const stepHostBusyShareOf = (host: readonly HostSample[], step: Phase): number | undefined =>
    busyShareOf(inside(byTime(host), step))

type StepRates = { rates: number[]; incomplete: boolean }

function gappedIn(window: readonly MetricSample[], step: Phase): boolean {
    const edges = [step.from, ...window.map(({ at }) => at), step.to]
    return (
        spanOf(window) <= 0 ||
        edges.some((at, i) => i > 0 && at - edges[i - 1] > SCRAPE_GAP_MS) ||
        window.some(({ startedAt }) => startedAt * 1000 > step.from)
    )
}

function stepRatesOf(replicas: readonly MetricSample[][], read: Counter, step: Phase): StepRates {
    const rates: number[] = []
    let incomplete = false
    for (const ofReplica of replicas) {
        const window = inside(ofReplica, step)
        const span = spanOf(window)
        incomplete ||= gappedIn(window, step)
        if (span > 0) {
            rates.push(increaseOf(window, read, window[0].at) / seconds(span))
        }
    }
    return { rates, incomplete }
}

const measuredOf = (value: number, incomplete: boolean): Measured => ({
    value,
    ...(incomplete ? { incomplete: true as const } : {}),
})

function stepClaimRate(samples: readonly MetricSample[], queue: string, step: Phase): Measured {
    const claiming = replicasOf(samples).filter((series) => series.some(({ processed }) => queue in processed))
    const { rates, incomplete } = stepRatesOf(claiming, ({ processed }) => processed[queue] ?? 0, step)
    return measuredOf(
        rates.reduce((sum, rate) => sum + rate, 0),
        incomplete
    )
}

const stepCpuOf = (ofRole: readonly MetricSample[], step: Phase): StepRates =>
    stepRatesOf(replicasOf(ofRole), ({ cpuSeconds }) => cpuSeconds, step)

type ScaledPhase = { scale: number; step: Phase }

const stepPhasesOf = (drive: DriveWindow, steps: readonly Step[]): ScaledPhase[] =>
    steps.flatMap(({ scale, fromMs, toMs }) => {
        const step = { from: drive.startedAt + fromMs, to: Math.min(drive.startedAt + toMs, drive.endedAt) }
        return step.to <= step.from ? [] : [{ scale, step }]
    })

const perRoleStep = (
    samples: readonly MetricSample[],
    drive: DriveWindow,
    steps: readonly Step[],
    read: (ofRole: readonly MetricSample[], step: Phase) => Measured[]
): Measured[] => {
    const roles = [...byRole(samples)].sort(([a], [b]) => a.localeCompare(b))
    return stepPhasesOf(drive, steps).flatMap(({ scale, step }) =>
        roles.flatMap(([role, ofRole]) =>
            read(ofRole, step).map((measured) => ({ key: `${role}_${scale}x`, ...measured }))
        )
    )
}

const meanBackendsOf = (
    activity: readonly ActivitySample[],
    step: Phase,
    keyOf: (backend: WriterBackends[number]) => string | undefined
): Measured[] => {
    const taken = inside(activity, step)
    const read = taken.flatMap((sample) => ('backends' in sample ? [sample.backends] : []))
    const failed = taken.find((sample) => 'error' in sample)
    if (taken.length === 0) {
        return [{ value: null, censored: true, unmeasured: 'no pg_stat_activity read landed in the step' }]
    }
    if (read.length === 0 && failed !== undefined && 'error' in failed) {
        return [
            {
                value: null,
                censored: true,
                unmeasured: `every pg_stat_activity read in the step failed: ${failed.error}`,
            },
        ]
    }
    const totals = new Map<string, number>()
    for (const backend of read.flat()) {
        const key = keyOf(backend)
        if (key !== undefined) {
            totals.set(key, (totals.get(key) ?? 0) + backend.count)
        }
    }
    if (totals.size === 0 && read.length < taken.length) {
        return [measuredOf(0, true)]
    }
    return [...totals]
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([key, total]) => ({ key, ...measuredOf(total / read.length, read.length < taken.length) }))
}

const perWriterStep =
    (keyOf: (backend: WriterBackends[number]) => string | undefined): MeasurementDefinition['measure'] =>
    ({ activity = [], drive, steps }) =>
        stepPhasesOf(drive, steps).flatMap(({ scale, step }) =>
            meanBackendsOf(activity, step, keyOf).map(({ key, ...measured }) => ({
                key: key === undefined ? `${scale}x` : `${key}_${scale}x`,
                ...measured,
            }))
        )

export type Baseline = {
    seconds: number
    scrapedSeconds: number
    claimsPerSecond: Record<string, number>
    newJobsPerSecond?: number
    hostBusyShare?: number
}

export function baselineOf({
    samples,
    queue,
    host,
    drive,
    timeline,
}: Pick<MeasureEvidence, 'samples' | 'queue' | 'host' | 'drive' | 'timeline'>): Baseline {
    const { baseline } = phasesOf(drive, timeline)
    const length = seconds(baseline.to - baseline.from)
    const scraped = scrapedSeconds(samples, baseline)
    if (length < MIN_BASELINE_SECONDS) {
        return { seconds: length, scrapedSeconds: scraped, claimsPerSecond: {} }
    }
    const queues = scraped < MIN_BASELINE_SECONDS ? [] : queuesOf(samples)
    const claimsPerSecond = Object.fromEntries(queues.map((name) => [name, claimRate(samples, name, baseline)]))
    const inserted = openedAt(counted(queue), baseline)
    const insertedSpan = openedSpanOf(inserted)
    const openedHost = openedAt(byTime(host), baseline)
    const hostBusyShare = busyShareOf(openedHost.window, openedHost.before)
    return {
        seconds: length,
        scrapedSeconds: scraped,
        claimsPerSecond,
        ...(insertedSpan > 0
            ? {
                  newJobsPerSecond:
                      (inserted.window.at(-1)!.inserted -
                          inserted.window[0].inserted -
                          inserted.before(({ inserted }) => inserted)) /
                      seconds(insertedSpan),
              }
            : {}),
        ...(hostBusyShare === undefined ? {} : { hostBusyShare }),
    }
}

export const RECOVERY_BAR_MULTIPLE = 2
const SERIES_WINDOW_MS = 60_000
const WRITER_PROBE_GAP_MS = 10_000
const WRITER_PROBE_LONGEST_IDLE_MS = 1_500

type WindowP99 = { value: number | null; clean: boolean; censored?: true; incomplete?: true; unmeasured?: string }

type SeriesPoint = {
    offsetS: number
    value: number | null
    recovered: boolean
    censored?: true
    incomplete?: true
    unmeasured?: string
}

const NO_WHOLE_MINUTE = 'the valve phase holds no whole minute'
const UNBOUNDED_PICKUPS = "scrape windows cannot bound a minute's pickups"

type Series = {
    baseline: number | null
    bar: number | null
    unmeasured?: string
    points: SeriesPoint[]
    valve: Phase
}

const recentBaselineOf = (baseline: Phase): Phase | undefined =>
    seconds(baseline.to - baseline.from) < MIN_BASELINE_SECONDS
        ? undefined
        : { from: Math.max(baseline.from, baseline.to - ENVELOPE_MS), to: baseline.to }

function windowsOf(phase: Phase): Phase[] {
    const windows: Phase[] = []
    for (let from = phase.from; from < phase.to; from += SERIES_WINDOW_MS) {
        windows.push({ from, to: Math.min(from + SERIES_WINDOW_MS, phase.to) })
    }
    return windows
}

function seriesOver(
    { drive, timeline }: Pick<MeasureEvidence, 'drive' | 'timeline'>,
    p99: (window: Phase, baseline: boolean) => WindowP99,
    { wholeMinutes = false } = {}
): Series | undefined {
    const { baseline, valve } = phasesOf(drive, timeline)
    const recent = recentBaselineOf(baseline)
    if (valve === undefined || recent === undefined) {
        return undefined
    }
    const reference = p99(recent, true)
    const usable = reference.value !== null && reference.clean && !reference.censored
    const bar = usable ? RECOVERY_BAR_MULTIPLE * reference.value! : null
    const judged = wholeMinutes
        ? {
              from: valve.from,
              to: valve.from + Math.floor((valve.to - valve.from) / SERIES_WINDOW_MS) * SERIES_WINDOW_MS,
          }
        : valve
    const windows = windowsOf(judged)
    const points =
        windows.length === 0
            ? [{ offsetS: 0, value: null, recovered: false, censored: true as const, unmeasured: NO_WHOLE_MINUTE }]
            : windows.map((window): SeriesPoint => {
                  const { value, clean, censored, incomplete, unmeasured } = p99(window, false)
                  return {
                      offsetS: seconds(window.from - valve.from),
                      value,
                      recovered: bar !== null && value !== null && clean && value <= bar,
                      ...(censored ? { censored } : {}),
                      ...(incomplete ? { incomplete } : {}),
                      ...(unmeasured ? { unmeasured } : {}),
                  }
              })
    return {
        baseline: usable ? reference.value : null,
        bar,
        ...(reference.unmeasured ? { unmeasured: reference.unmeasured } : {}),
        points,
        valve,
    }
}

const valueOf = (value: number | null, censored?: true): Value =>
    value === null ? { value, censored: true } : censored ? { value, censored } : { value }

const pointsOf = ({ baseline, bar, unmeasured, points }: Series, prefix = ''): Measured[] => [
    { key: `${prefix}baseline`, ...valueOf(baseline), ...(unmeasured ? { unmeasured } : {}) },
    { key: `${prefix}bar`, ...valueOf(bar), ...(unmeasured ? { unmeasured } : {}) },
    ...points.map(
        ({ offsetS, value, censored, incomplete, unmeasured }): Measured => ({
            key: `${prefix}t${offsetS}`,
            ...valueOf(value, censored),
            ...(incomplete ? { incomplete } : {}),
            ...(unmeasured ? { unmeasured } : {}),
        })
    ),
]

function recoveryOf({ bar, points }: Series, unknown?: string): Measured {
    if (unknown !== undefined) {
        return { value: null, censored: true, unmeasured: unknown }
    }
    const lastUnrecovered = points.findLastIndex(({ recovered }) => !recovered)
    return bar === null || lastUnrecovered === points.length - 1
        ? { value: null, censored: true }
        : { value: lastUnrecovered < 0 ? 0 : points[lastUnrecovered + 1].offsetS }
}

function writeLatencySeries({ writer, drive, timeline }: MeasureEvidence): Series | undefined {
    const ends = writer.map(committedAt).sort((a, b) => a - b)
    return seriesOver(
        { drive, timeline },
        (window, baseline) => {
            const ended = writer.filter(
                (sample) => within(window, committedAt(sample)) && (!baseline || within(window, sample.at))
            )
            const committed = ended
                .filter(({ ok }) => ok)
                .map(({ latencyMs }) => latencyMs)
                .sort((a, b) => a - b)
            const failed = ended.some(({ ok }) => !ok)
            const previous = ends.findLast((at) => at < window.from) ?? window.from
            const next = ends.find((at) => at >= window.to) ?? window.to
            const inside = baseline ? ended.map(committedAt) : ends.filter((at) => within(window, at))
            const bounds = [previous, ...inside.sort((a, b) => a - b), next]
            const silent = bounds.some((at, i) => i > 0 && at - bounds[i - 1] > WRITER_PROBE_GAP_MS)
            return {
                value: committed.length === 0 ? null : nearestRank(committed, 0.99),
                clean: !silent && !failed,
                ...(silent ? { incomplete: true as const } : {}),
            }
        },
        { wholeMinutes: true }
    )
}

function pickupSeries({ samples, drive, timeline }: MeasureEvidence): [string, Series][] {
    return Object.entries(WORKER_OF).flatMap(([queue, role]) => {
        if (!samples.some((sample) => sample.role === role)) {
            return []
        }
        const series = seriesOver({ drive, timeline }, () => ({
            value: null,
            clean: false,
            censored: true,
            unmeasured: UNBOUNDED_PICKUPS,
        }))
        return series ? [[queue, series] as [string, Series]] : []
    })
}

type PhaseName = 'valve' | 'failback'

const inPhase = (
    name: string,
    unit: string,
    phaseName: PhaseName,
    measured: (evidence: MeasureEvidence, phase: Phase, phases: Phases) => Measured[]
): MeasurementDefinition => ({
    name,
    params: z.object({}).strict(),
    unit,
    measure: (evidence) => {
        const phases = phasesOf(evidence.drive, evidence.timeline)
        const phase = phases[phaseName]
        return phase === undefined ? [] : measured(evidence, phase, phases)
    },
})

function sinceIntent(
    drive: DriveWindow,
    timeline: readonly ValveTimelineEntry[],
    name: ObservationName
): Measured[] | undefined {
    const journalled = appliedDuring(drive, timeline).find(({ observations }) => observations)
    if (journalled === undefined) {
        return undefined
    }
    const observation = journalled.observations!.find((candidate) => candidate.name === name)
    return observation === undefined
        ? [{ value: null, censored: true }]
        : [{ value: seconds(Date.parse(observation.at) - Date.parse(journalled.intentAt!)) }]
}

const observed = (name: string, observation: ObservationName): MeasurementDefinition => ({
    name,
    params: z.object({}).strict(),
    unit: 's',
    measure: ({ drive, timeline }) => sinceIntent(drive, timeline, observation) ?? [],
})

export const RECOVERY_MEASUREMENTS: MeasurementDefinition[] = [
    observed('seconds_to_cluster_writer', 'cluster_writer'),
    observed('seconds_to_sql_writer', 'sql_writer'),
    inPhase('writer_unavailable_seconds', 's', 'valve', ({ writer }, phase) => writerUnavailable(writer, phase)),
    inPhase('failback_writer_unavailable_seconds', 's', 'failback', ({ writer }, phase) =>
        writerUnavailable(writer, phase)
    ),
    inPhase(
        'seconds_to_first_probe_commit',
        's',
        'valve',
        ({ writer, drive, timeline }, phase) =>
            sinceIntent(drive, timeline, 'first_probe_commit') ?? firstCommitAfterFailure(writer, phase)
    ),
    inPhase('queue_lag_peak_seconds', 's', 'valve', ({ queue }, phase) => {
        const ages = counted(queue)
            .filter(({ at }) => within(phase, at))
            .map(({ oldestDueSeconds }) => oldestDueSeconds)
        return ages.length === 0
            ? []
            : [{ value: maxOf(ages), ...(readThroughout(queue, phase) ? {} : { incomplete: true as const }) }]
    }),
    inPhase('drain_seconds', 's', 'valve', ({ queue }, phase, { baseline }) => drain(queue, baseline, phase)),
    inPhase('failback_drain_seconds', 's', 'failback', ({ queue }, phase, { baseline }) =>
        drain(queue, baseline, phase)
    ),
    inPhase('pg_client_errors', 'errors', 'valve', ({ samples, missed }, phase) => [
        phaseIncrease(samples, missed, ({ pgClientErrors }) => pgClientErrors, phase),
    ]),
    inPhase('consumer_loop_errors', 'errors', 'valve', ({ samples, missed }, phase) => [
        phaseIncrease(samples, missed, ({ consumerLoopErrors }) => consumerLoopErrors, phase),
    ]),
    {
        name: 'write_latency_p99_ms',
        params: z.object({}).strict(),
        unit: 'ms',
        measure: (evidence) => {
            const series = writeLatencySeries(evidence)
            return series ? pointsOf(series) : []
        },
    },
    {
        name: 'write_latency_recovery_seconds',
        params: z.object({}).strict(),
        unit: 's',
        measure: (evidence) => {
            const series = writeLatencySeries(evidence)
            if (series === undefined) {
                return []
            }
            const { from, to } = series.valve
            const settled = from + Math.floor((to - from) / SERIES_WINDOW_MS) * SERIES_WINDOW_MS
            const inFlight = evidence.writer.some((sample) => sample.at < to && committedAt(sample) >= to)
            const unsettled = evidence.writer.some((sample) => {
                const end = committedAt(sample)
                const late = !sample.ok || (series.bar !== null && sample.latencyMs > series.bar)
                return settled < to && ((end >= settled && end < to && late) || (sample.at < settled && end >= settled))
            })
            const unsampled = settled < to && longestIdle(evidence.writer, settled, to) > WRITER_PROBE_LONGEST_IDLE_MS
            return [
                recoveryOf(
                    series,
                    inFlight
                        ? 'a write probe was in flight at the valve end'
                        : unsettled
                          ? 'a write after the last whole minute of the valve failed or passed the bar'
                          : unsampled
                            ? 'the remainder after the last whole minute of the valve went unsampled'
                            : undefined
                ),
            ]
        },
    },
    {
        name: 'pickup_p99_seconds',
        params: z.object({}).strict(),
        unit: 's',
        measure: (evidence) => pickupSeries(evidence).flatMap(([queue, series]) => pointsOf(series, `${queue}_`)),
    },
    {
        name: 'pickup_recovery_seconds',
        params: z.object({}).strict(),
        unit: 's',
        measure: (evidence) =>
            pickupSeries(evidence).map(([key]) => ({
                key,
                value: null,
                censored: true as const,
                unmeasured: UNBOUNDED_PICKUPS,
            })),
    },
    {
        name: 'baseline_claims_per_second',
        params: z.object({}).strict(),
        unit: 'jobs/s',
        measure: (evidence) =>
            Object.entries(baselineOf(evidence).claimsPerSecond).map(([key, value]) => ({ key, value })),
    },
    {
        name: 'step_claims_per_second',
        params: z.object({}).strict(),
        unit: 'jobs/s',
        measure: ({ samples, drive, steps }) =>
            stepPhasesOf(drive, steps).flatMap(({ scale, step }) =>
                queuesOf(samples).map((queue) => ({
                    key: `${queue}_${scale}x`,
                    ...stepClaimRate(samples, queue, step),
                }))
            ),
    },
    {
        name: 'step_writer_backends',
        params: z.object({}).strict(),
        unit: 'backends',
        measure: perWriterStep(({ state }) => state.replace(/ /g, '_')),
    },
    {
        name: 'step_writer_active_waits',
        params: z.object({}).strict(),
        unit: 'backends',
        measure: perWriterStep(({ state, wait }) => (state === 'active' ? wait : undefined)),
    },
    {
        name: 'step_host_busy_percent',
        params: z.object({}).strict(),
        unit: '%',
        measure: ({ host, drive, steps }) =>
            stepPhasesOf(drive, steps).flatMap(({ scale, step }) => {
                const share = stepHostBusyShareOf(host, step)
                return share === undefined ? [] : [{ key: `${scale}x`, value: share * 100 }]
            }),
    },
    {
        name: 'step_role_cpu_cores',
        params: z.object({}).strict(),
        unit: 'cores',
        measure: ({ samples, drive, steps }) =>
            perRoleStep(samples, drive, steps, (ofRole, step) => {
                const { rates, incomplete } = stepCpuOf(ofRole, step)
                return [
                    measuredOf(
                        rates.reduce((sum, rate) => sum + rate, 0),
                        incomplete
                    ),
                ]
            }),
    },
    {
        name: 'step_role_busiest_cpu_cores',
        params: z.object({}).strict(),
        unit: 'cores',
        measure: ({ samples, drive, steps }) =>
            perRoleStep(samples, drive, steps, (ofRole, step) => {
                const { rates, incomplete } = stepCpuOf(ofRole, step)
                return [measuredOf(Math.max(0, ...rates), incomplete)]
            }),
    },
    {
        name: 'baseline_new_jobs_per_second',
        params: z.object({}).strict(),
        unit: 'jobs/s',
        measure: (evidence) => {
            const { newJobsPerSecond } = baselineOf(evidence)
            return newJobsPerSecond === undefined ? [] : [{ value: newJobsPerSecond }]
        },
    },
]

export const MEASUREMENTS: MeasurementDefinition[] = [
    roleCpuSeconds,
    roleRssMaxBytes,
    deliveryLatencyMs,
    roleExitMs,
    leaseReclaimMs,
    resentInvocations,
    counterDrift,
    ...RECOVERY_MEASUREMENTS,
]

export function measure(measurements: Named[], evidence: MeasureEvidence): Measurement[] {
    return measurements.flatMap(({ name }) => {
        const definition = MEASUREMENTS.find((measurement) => measurement.name === name)
        if (!definition) {
            throw new Error(`No measurement ${name}`)
        }
        return definition.measure(evidence).map((value) => ({ name, unit: definition.unit, ...value }))
    })
}

function gauge(text: string, name: string): number | undefined {
    const line = text.split('\n').find((candidate) => new RegExp(`^${name}(\\{[^}]*\\})? `).test(candidate))
    const value = line === undefined ? NaN : Number(line.slice(line.lastIndexOf(' ') + 1))
    return Number.isFinite(value) ? value : undefined
}

const SERIES = /^(\w+)(?:\{([^}]*)\})? (\S+)/

function seriesOf(text: string, name: string): { labels: Record<string, string>; value: number }[] {
    return text.split('\n').flatMap((line) => {
        const match = SERIES.exec(line)
        const value = Number(match?.[3])
        if (match === null || match[1] !== name || !Number.isFinite(value)) {
            return []
        }
        const labels = Object.fromEntries([...(match[2] ?? '').matchAll(/(\w+)="([^"]*)"/g)].map(([, k, v]) => [k, v]))
        return [{ labels, value }]
    })
}

const totalOf = (text: string, name: string): number => seriesOf(text, name).reduce((sum, { value }) => sum + value, 0)

const CYCLOTRON_SOURCE = 'postgres-v2'

function processedOf(text: string): Record<string, number> {
    const processed: Record<string, number> = {}
    for (const { labels, value } of seriesOf(text, 'cdp_cyclotron_jobs_processed')) {
        if (labels.source === CYCLOTRON_SOURCE && labels.queue !== undefined) {
            processed[labels.queue] = (processed[labels.queue] ?? 0) + value
        }
    }
    return processed
}

function latenessOf(text: string): Record<string, Record<string, number>> {
    const lateness: Record<string, Record<string, number>> = {}
    for (const { labels, value } of seriesOf(text, 'cdp_cyclotron_job_lateness_seconds_bucket')) {
        if (labels.queue !== undefined && labels.le !== undefined) {
            const buckets = (lateness[labels.queue] ??= {})
            buckets[labels.le] = (buckets[labels.le] ?? 0) + value
        }
    }
    return lateness
}

export function sampleOf({ role, replica }: Target, at: number, text: string): MetricSample | undefined {
    const startedAt = gauge(text, 'process_start_time_seconds')
    const cpuSeconds = gauge(text, 'process_cpu_seconds_total')
    const rssBytes = gauge(text, 'process_resident_memory_bytes')
    return startedAt === undefined || cpuSeconds === undefined || rssBytes === undefined
        ? undefined
        : {
              role,
              replica,
              at,
              startedAt,
              cpuSeconds,
              rssBytes,
              processed: processedOf(text),
              pgClientErrors: totalOf(text, 'cdp_cyclotron_v2_pg_client_errors_total'),
              consumerLoopErrors: totalOf(text, 'cdp_cyclotron_v2_consumer_loop_errors_total'),
              janitorStalled: totalOf(text, 'cdp_cyclotron_v2_janitor_stalled'),
              lateness: latenessOf(text),
          }
}

const FIRST_GUEST_FIELD = 8

export function hostSampleOf(at: number, procStat: string): HostSample | undefined {
    const line = procStat.split('\n').find((candidate) => /^cpu\s/.test(candidate))
    const ticks = line?.trim().split(/\s+/).slice(1).map(Number) ?? []
    if (ticks.length < 5 || ticks.some((tick) => !Number.isFinite(tick))) {
        return undefined
    }
    const totalTicks = ticks.slice(0, FIRST_GUEST_FIELD).reduce((sum, tick) => sum + tick, 0)
    return { at, busyTicks: totalTicks - ticks[3] - ticks[4], totalTicks }
}

export type Sampler = {
    sampledFrom: number
    taken(): readonly MetricSample[]
    host(): readonly HostSample[]
    stop(): Promise<Sampled>
}

type Target = ReplicaOf & { metricsUrl: string }

export type SamplerOptions = { baselineWithinMs?: number; readHostStat?: () => string }

const readProcStat = (): string => readFileSync('/proc/stat', 'utf8')

export async function startSampler(
    targets: Target[],
    { baselineWithinMs = BASELINE_WITHIN_MS, readHostStat = readProcStat }: SamplerOptions = {}
): Promise<Sampler> {
    const samples: MetricSample[] = []
    const missed: MissedScrape[] = []
    const host: HostSample[] = []
    const sampleHost = (): void => {
        const at = Date.now()
        let sample: HostSample | undefined
        try {
            sample = hostSampleOf(at, readHostStat())
        } catch {
            sample = undefined
        }
        if (sample) {
            host.push(sample)
        }
    }
    const stopped = new AbortController()
    const scrape = async (some: Target[], timeoutMs = SCRAPE_TIMEOUT_MS): Promise<MissedScrape[]> => {
        const failed: MissedScrape[] = []
        await Promise.all(
            some.map(async (target) => {
                const at = Date.now()
                const text = await internalFetch(target.metricsUrl, { timeoutMs })
                    .then((response) => (response.status === 200 ? response.text() : ''))
                    .catch(() => '')
                const fetchedAt = Date.now()
                const sample = sampleOf(target, at, text)
                if (sample) {
                    samples.push({ ...sample, fetchedAt })
                } else {
                    failed.push({ role: target.role, replica: target.replica, at })
                }
            })
        )
        return failed
    }
    const scrapeAll = async (): Promise<void> => {
        sampleHost()
        missed.push(...(await scrape(targets)))
    }
    const sampledFrom = Date.now()
    const deadline = sampledFrom + baselineWithinMs
    let missing = targets
    for (;;) {
        await scrape(missing, Math.min(SCRAPE_TIMEOUT_MS, Math.max(deadline - Date.now(), 1)))
        missing = targets.filter(
            (target) => !samples.some((sample) => sample.role === target.role && sample.replica === target.replica)
        )
        if (missing.length === 0) {
            break
        }
        if (Date.now() + BASELINE_RETRY_MS > deadline) {
            throw new Error(`No metrics baseline from ${missing.map(nameOf).join(', ')} within ${baselineWithinMs} ms`)
        }
        await sleep(BASELINE_RETRY_MS)
    }
    sampleHost()
    const sampling = (async () => {
        while (!stopped.signal.aborted) {
            await sleep(SAMPLE_INTERVAL_MS, undefined, { signal: stopped.signal }).catch(() => undefined)
            if (!stopped.signal.aborted) {
                await scrapeAll()
            }
        }
    })()
    let stopping: Promise<Sampled> | undefined
    return {
        sampledFrom,
        taken: () => samples,
        host: () => host,
        stop: () =>
            (stopping ??= (async () => {
                stopped.abort()
                await sampling
                await scrapeAll()
                return { samples, missed, host }
            })()),
    }
}
