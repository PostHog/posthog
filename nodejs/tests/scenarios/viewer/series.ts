import { isAccepted } from '../judge/invariants'
import type { JournalEntry } from '../judge/judge'
import { LatencyEvidence, MetricSample, QueueSample, deliveryLatenciesOf, nearestRank } from '../judge/measurements'
import type { WriterSample } from '../probe/writer-probe'
import type { TruthRecord } from '../provider-edge'

export type RolePoint = { at: number; cpuPercent: number; processedPerSecond: number; rssMb: number }

export type RoleSeries = { role: string; replicas: number; restarts: number[]; points: RolePoint[] }

export type QueuePoint = { at: number; due: number; running: number; oldestDueSeconds: number }

export type WriterPoint = { at: number; latencyMs: number; ok: boolean }

export type FlowPoint = {
    at: number
    offeredEvents: number
    offeredTransactional: number
    refused: number
    emailOk: number
    emailFaulted: number
    webhookOk: number
    webhookFaulted: number
    feedback: number
    latencyP50Ms: number | null
    latencyP95Ms: number | null
}

export type Series = {
    bucketMs: number
    roles: RoleSeries[]
    queue: QueuePoint[]
    writer: WriterPoint[]
    flow: FlowPoint[]
}

export type Evidence = {
    samples: readonly MetricSample[]
    queue: readonly QueueSample[]
    writer: readonly WriterSample[]
    journal: readonly (Pick<JournalEntry, 'kind'> & LatencyEvidence['journal'][number])[]
    truth: readonly (Pick<TruthRecord, 'kind' | 'fault'> & LatencyEvidence['truth'][number])[]
}

const BUCKET_MS = 5000

const bucketOf = (at: number, bucketMs: number): number => Math.floor(at / bucketMs) * bucketMs

const percentileOf = (sorted: number[], share: number): number | null =>
    sorted.length === 0 ? null : nearestRank(sorted, share)

const processedOf = (sample: MetricSample): number =>
    Object.values(sample.processed).reduce((sum, count) => sum + count, 0)

type Weighted = { weightMs: number; cpuPercent: number; processedPerSecond: number; rssMb: number }

function replicaBucketsOf(ofReplica: readonly MetricSample[]): { restarts: number[]; buckets: Map<number, RolePoint> } {
    const restarts: number[] = []
    const weighted = new Map<number, Weighted>()
    for (let i = 1; i < ofReplica.length; i++) {
        const [before, after] = [ofReplica[i - 1], ofReplica[i]]
        if (before.startedAt !== after.startedAt) {
            restarts.push(after.startedAt * 1000)
            continue
        }
        const seconds = (after.at - before.at) / 1000
        if (seconds <= 0) {
            continue
        }
        const cpuPercent = ((after.cpuSeconds - before.cpuSeconds) / seconds) * 100
        const processedPerSecond = Math.max(processedOf(after) - processedOf(before), 0) / seconds
        const rssMb = after.rssBytes / 1024 / 1024
        for (let at = bucketOf(before.at, BUCKET_MS); at < after.at; at += BUCKET_MS) {
            const weightMs = Math.min(after.at, at + BUCKET_MS) - Math.max(before.at, at)
            const sum = weighted.get(at) ?? { weightMs: 0, cpuPercent: 0, processedPerSecond: 0, rssMb: 0 }
            sum.weightMs += weightMs
            sum.cpuPercent += cpuPercent * weightMs
            sum.processedPerSecond += processedPerSecond * weightMs
            sum.rssMb += rssMb * weightMs
            weighted.set(at, sum)
        }
    }
    const buckets = new Map(
        [...weighted].map(([at, sum]) => [
            at,
            {
                at,
                cpuPercent: sum.cpuPercent / sum.weightMs,
                processedPerSecond: sum.processedPerSecond / sum.weightMs,
                rssMb: sum.rssMb / sum.weightMs,
            },
        ])
    )
    return { restarts, buckets }
}

export function roleSeriesOf(samples: readonly MetricSample[]): RoleSeries[] {
    const byReplica = Map.groupBy(
        [...samples].sort((a, b) => a.at - b.at),
        ({ role, replica }) => `${role}\u0000${replica}`
    )
    type RoleEntry = { replicas: number; restarts: number[]; buckets: Map<number, RolePoint> }
    const byRole = new Map<string, RoleEntry>()
    for (const ofReplica of byReplica.values()) {
        const role = ofReplica[0].role
        const entry: RoleEntry = byRole.get(role) ?? { replicas: 0, restarts: [], buckets: new Map() }
        byRole.set(role, entry)
        entry.replicas += 1
        const { restarts, buckets } = replicaBucketsOf(ofReplica)
        entry.restarts.push(...restarts)
        for (const [at, point] of buckets) {
            const sum = entry.buckets.get(at) ?? { at, cpuPercent: 0, processedPerSecond: 0, rssMb: 0 }
            sum.cpuPercent += point.cpuPercent
            sum.processedPerSecond += point.processedPerSecond
            sum.rssMb += point.rssMb
            entry.buckets.set(at, sum)
        }
    }
    return [...byRole.entries()]
        .map(([role, { replicas, restarts, buckets }]) => ({
            role,
            replicas,
            restarts: restarts.sort((a, b) => a - b),
            points: [...buckets.values()].sort((a, b) => a.at - b.at),
        }))
        .sort((a, b) => a.role.localeCompare(b.role))
}

export function queueSeriesOf(queue: readonly QueueSample[]): QueuePoint[] {
    return queue.flatMap((sample) =>
        'error' in sample
            ? []
            : [
                  {
                      at: sample.at,
                      due: sample.due,
                      running: sample.running,
                      oldestDueSeconds: sample.oldestDueSeconds,
                  },
              ]
    )
}

export function writerSeriesOf(writer: readonly WriterSample[]): WriterPoint[] {
    return writer.map(({ at, latencyMs, ok }) => ({ at, latencyMs, ok }))
}

export function flowSeriesOf({ journal, truth }: Pick<Evidence, 'journal' | 'truth'>): FlowPoint[] {
    const buckets = new Map<number, FlowPoint & { latencies: number[] }>()
    const pointAt = (at: number): FlowPoint & { latencies: number[] } => {
        const key = bucketOf(at, BUCKET_MS)
        const point = buckets.get(key) ?? {
            at: key,
            offeredEvents: 0,
            offeredTransactional: 0,
            refused: 0,
            emailOk: 0,
            emailFaulted: 0,
            webhookOk: 0,
            webhookFaulted: 0,
            feedback: 0,
            latencyP50Ms: null,
            latencyP95Ms: null,
            latencies: [],
        }
        buckets.set(key, point)
        return point
    }
    for (const { offeredAt: at, kind, answer } of journal) {
        const point = pointAt(at)
        if (kind === 'event') {
            point.offeredEvents += 1
        } else {
            point.offeredTransactional += 1
        }
        if (!answer.accepted) {
            point.refused += 1
        }
    }
    for (const record of truth) {
        const at = Date.parse(record.at)
        const point = pointAt(at)
        if (record.kind === 'ses.feedback') {
            point.feedback += 1
            continue
        }
        const email = record.kind === 'ses.send'
        if (isAccepted(record.status) && record.fault === undefined) {
            point[email ? 'emailOk' : 'webhookOk'] += 1
        } else {
            point[email ? 'emailFaulted' : 'webhookFaulted'] += 1
        }
    }
    for (const { offeredAt, latencyMs } of deliveryLatenciesOf({ journal, truth })) {
        pointAt(offeredAt).latencies.push(latencyMs)
    }
    return [...buckets.values()]
        .sort((a, b) => a.at - b.at)
        .map(({ latencies, ...point }) => {
            const sorted = latencies.sort((a, b) => a - b)
            return { ...point, latencyP50Ms: percentileOf(sorted, 0.5), latencyP95Ms: percentileOf(sorted, 0.95) }
        })
}

export function seriesOf(evidence: Evidence): Series {
    return {
        bucketMs: BUCKET_MS,
        roles: roleSeriesOf(evidence.samples),
        queue: queueSeriesOf(evidence.queue),
        writer: writerSeriesOf(evidence.writer),
        flow: flowSeriesOf(evidence),
    }
}
