import type { JournalEntry } from '../judge/judge'
import type { MetricSample, QueueSample } from '../judge/measurements'
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
    journal: readonly Pick<JournalEntry, 'unitId' | 'kind' | 'offeredAt' | 'answer'>[]
    truth: readonly Pick<TruthRecord, 'at' | 'kind' | 'unitId' | 'actionId' | 'status' | 'fault'>[]
}

const FLOW_BUCKET_MS = 5000

const isOk = (status: number): boolean => status >= 200 && status < 300

const bucketOf = (at: number, bucketMs: number): number => Math.floor(at / bucketMs) * bucketMs

function percentile(sorted: number[], share: number): number | null {
    if (sorted.length === 0) {
        return null
    }
    return sorted[Math.min(sorted.length - 1, Math.ceil(share * sorted.length) - 1)]
}

const processedOf = (sample: MetricSample): number =>
    Object.values(sample.processed).reduce((sum, count) => sum + count, 0)

// Rates come from pairs of scrapes of one process, so a restarted replica, whose counters start
// again from zero, contributes no rate across its restart.
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
        for (let i = 1; i < ofReplica.length; i++) {
            const [before, after] = [ofReplica[i - 1], ofReplica[i]]
            if (before.startedAt !== after.startedAt) {
                // A process reports its start in seconds.
                entry.restarts.push(after.startedAt * 1000)
                continue
            }
            const seconds = (after.at - before.at) / 1000
            if (seconds <= 0) {
                continue
            }
            const at = bucketOf(after.at, FLOW_BUCKET_MS)
            const point = entry.buckets.get(at) ?? { at, cpuPercent: 0, processedPerSecond: 0, rssMb: 0 }
            point.cpuPercent += ((after.cpuSeconds - before.cpuSeconds) / seconds) * 100
            point.processedPerSecond += Math.max(processedOf(after) - processedOf(before), 0) / seconds
            point.rssMb += after.rssBytes / 1024 / 1024
            entry.buckets.set(at, point)
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

// Latency runs from a unit's offer to the edge's first 2xx for each of its deliveries, the same
// span `delivery_latency_ms` measures, bucketed by when the unit was offered.
export function flowSeriesOf({ journal, truth }: Pick<Evidence, 'journal' | 'truth'>): FlowPoint[] {
    const buckets = new Map<number, FlowPoint & { latencies: number[] }>()
    const pointAt = (at: number): FlowPoint & { latencies: number[] } => {
        const key = bucketOf(at, FLOW_BUCKET_MS)
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
    const offeredAt = new Map(journal.map(({ unitId, offeredAt }) => [unitId, offeredAt]))
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
    const firstOk = new Map<string, number>()
    for (const record of truth) {
        const at = Date.parse(record.at)
        const point = pointAt(at)
        if (record.kind === 'ses.feedback') {
            point.feedback += 1
            continue
        }
        const email = record.kind === 'ses.send'
        if (isOk(record.status) && record.fault === undefined) {
            point[email ? 'emailOk' : 'webhookOk'] += 1
            const key = `${record.unitId}/${record.actionId}`
            if (record.unitId !== undefined && !firstOk.has(key)) {
                firstOk.set(key, at)
                const offered = offeredAt.get(record.unitId)
                if (offered !== undefined) {
                    pointAt(offered).latencies.push(at - offered)
                }
            }
        } else {
            point[email ? 'emailFaulted' : 'webhookFaulted'] += 1
        }
    }
    return [...buckets.values()]
        .sort((a, b) => a.at - b.at)
        .map(({ latencies, ...point }) => {
            const sorted = latencies.sort((a, b) => a - b)
            return { ...point, latencyP50Ms: percentile(sorted, 0.5), latencyP95Ms: percentile(sorted, 0.95) }
        })
}

export function seriesOf(evidence: Evidence): Series {
    return {
        bucketMs: FLOW_BUCKET_MS,
        roles: roleSeriesOf(evidence.samples),
        queue: queueSeriesOf(evidence.queue),
        writer: writerSeriesOf(evidence.writer),
        flow: flowSeriesOf(evidence),
    }
}
