import { readFileSync } from 'fs'
import { setTimeout as sleep } from 'timers/promises'
import { z } from 'zod'

import { internalFetch } from '~/common/utils/request'

import type { Named } from '../cards'
import type { Definition } from '../cards/definitions'
import { ReplicaOf, nameOf } from '../environment/identity'
import type { QueueCounts } from '../probe/cyclotron-probe'
import type { WriterSample } from '../probe/writer-probe'
import type { ValveTimelineEntry } from '../valves/valves'
import { deliveryKey } from './invariants'
import type { JudgeEvidence } from './invariants'

export type MetricSample = {
    role: string
    replica: number
    at: number
    startedAt: number
    cpuSeconds: number
    rssBytes: number
    processed: Record<string, number>
    pgClientErrors: number
    consumerLoopErrors: number
}

export type MissedScrape = { role: string; replica: number; at: number }

export type HostSample = { at: number; busyTicks: number; totalTicks: number }

export type Sampled = { samples: MetricSample[]; missed: MissedScrape[]; host: HostSample[] }

export type QueueSample = { at: number } & (QueueCounts | { error: string })

export type Probed = { writer: WriterSample[]; queue: QueueSample[] }

export type DriveWindow = { startedAt: number; endedAt: number }

type Value = { value: number; censored?: true } | { value: null; censored: true }

type Measured = { key?: string; incomplete?: true } & Value

export type Measurement = { name: string; unit: string } & Measured

export type MeasureEvidence = JudgeEvidence &
    Readonly<Sampled> &
    Readonly<Probed> & { sampledFrom: number; drive: DriveWindow; timeline: readonly ValveTimelineEntry[] }

export type MeasurementDefinition = Definition & {
    unit: string
    measure(evidence: MeasureEvidence): Measured[]
}

const SAMPLE_INTERVAL_MS = 5000
const SCRAPE_TIMEOUT_MS = 2000
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

const cpuSecondsOf = (ofReplica: readonly MetricSample[], sampledFrom: number): number =>
    increaseOf(ofReplica, ({ cpuSeconds }) => cpuSeconds, sampledFrom)

export const roleCpuSeconds: MeasurementDefinition = {
    name: 'role_cpu_seconds',
    params: z.object({}).strict(),
    unit: 's',
    measure: ({ samples, missed, sampledFrom }) =>
        [...byRole(samples)].map(([role, ofRole]) => {
            const replicas = [...Map.groupBy(ofRole, ({ replica }) => replica).values()]
            return {
                key: role,
                value: replicas.reduce((sum, ofReplica) => sum + cpuSecondsOf(ofReplica, sampledFrom), 0),
                ...(replicas.some((ofReplica) => lostCpu(ofReplica, missed)) ? { incomplete: true as const } : {}),
            }
        }),
}

export const roleRssMaxBytes: MeasurementDefinition = {
    name: 'role_rss_max_bytes',
    params: z.object({}).strict(),
    unit: 'bytes',
    measure: ({ samples, missed }) =>
        [...byRole(samples)].map(([role, ofRole]) => ({
            key: role,
            value: Math.max(...ofRole.map(({ rssBytes }) => rssBytes)),
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

export type Phase = { from: number; to: number }

export type Phases = { baseline: Phase; valve?: Phase; failback?: Phase }

export function phasesOf(drive: DriveWindow, timeline: readonly ValveTimelineEntry[]): Phases {
    const applied = timeline.flatMap(({ intentAt, releasedAt }) =>
        intentAt === undefined
            ? []
            : [{ intent: Date.parse(intentAt), released: releasedAt === undefined ? Infinity : Date.parse(releasedAt) }]
    )
    if (applied.length === 0) {
        return { baseline: { from: drive.startedAt, to: drive.endedAt } }
    }
    const intent = Math.max(Math.min(...applied.map(({ intent }) => intent)), drive.startedAt)
    const released = Math.max(...applied.map(({ released }) => released))
    return {
        baseline: { from: drive.startedAt, to: intent },
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
        const window = spanning(ofReplica, phase)
        const span = spanOf(window)
        return span <= 0 ? sum : sum + increaseOf(window, read, window[0].at) / seconds(span)
    }, 0)
}

function scrapedSeconds(samples: readonly MetricSample[], phase: Phase): number {
    const spans = replicasOf(samples)
        .map((ofReplica) => spanning(ofReplica, phase))
        .filter((window) => window.length > 0)
        .map((window) => seconds(spanOf(window)))
    return spans.length === 0 ? 0 : Math.min(...spans)
}

export type Baseline = {
    seconds: number
    scrapedSeconds: number
    claimsPerSecond: Record<string, number>
    newJobsPerSecond?: number
    hostBusyShare?: number
}

export function baselineOf({ samples, queue, host, drive, timeline }: MeasureEvidence): Baseline {
    const { baseline } = phasesOf(drive, timeline)
    const length = seconds(baseline.to - baseline.from)
    const scraped = scrapedSeconds(samples, baseline)
    if (length < MIN_BASELINE_SECONDS) {
        return { seconds: length, scrapedSeconds: scraped, claimsPerSecond: {} }
    }
    const queues =
        scraped < MIN_BASELINE_SECONDS ? [] : [...new Set(samples.flatMap(({ processed }) => Object.keys(processed)))]
    const claimsPerSecond = Object.fromEntries(
        queues.map((name) => [name, phaseRate(samples, ({ processed }) => processed[name] ?? 0, baseline)])
    )
    const inserted = spanning(counted(queue), baseline)
    const hostSpan = spanning(byTime(host), baseline)
    const [firstHost, lastHost] = [hostSpan.at(0), hostSpan.at(-1)]
    return {
        seconds: length,
        scrapedSeconds: scraped,
        claimsPerSecond,
        ...(inserted.length > 1 && inserted.at(-1)!.at > inserted[0].at
            ? {
                  newJobsPerSecond:
                      (inserted.at(-1)!.inserted - inserted[0].inserted) /
                      seconds(inserted.at(-1)!.at - inserted[0].at),
              }
            : {}),
        ...(firstHost !== undefined && lastHost !== undefined && lastHost.totalTicks > firstHost.totalTicks
            ? {
                  hostBusyShare:
                      (lastHost.busyTicks - firstHost.busyTicks) / (lastHost.totalTicks - firstHost.totalTicks),
              }
            : {}),
    }
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

export const RECOVERY_MEASUREMENTS: MeasurementDefinition[] = [
    inPhase('writer_unavailable_seconds', 's', 'valve', ({ writer }, phase) => writerUnavailable(writer, phase)),
    inPhase('failback_writer_unavailable_seconds', 's', 'failback', ({ writer }, phase) =>
        writerUnavailable(writer, phase)
    ),
    inPhase('seconds_to_first_probe_commit', 's', 'valve', ({ writer }, phase) =>
        firstCommitAfterFailure(writer, phase)
    ),
    inPhase('queue_lag_peak_seconds', 's', 'valve', ({ queue }, phase) => {
        const ages = counted(queue)
            .filter(({ at }) => within(phase, at))
            .map(({ oldestDueSeconds }) => oldestDueSeconds)
        return ages.length === 0
            ? []
            : [{ value: Math.max(...ages), ...(readThroughout(queue, phase) ? {} : { incomplete: true as const }) }]
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
        name: 'baseline_claims_per_second',
        params: z.object({}).strict(),
        unit: 'jobs/s',
        measure: (evidence) =>
            Object.entries(baselineOf(evidence).claimsPerSecond).map(([key, value]) => ({ key, value })),
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

export type Sampler = { sampledFrom: number; stop(): Promise<Sampled> }

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
                const sample = sampleOf(target, at, text)
                if (sample) {
                    samples.push(sample)
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
        stop: () =>
            (stopping ??= (async () => {
                stopped.abort()
                await sampling
                await scrapeAll()
                return { samples, missed, host }
            })()),
    }
}
