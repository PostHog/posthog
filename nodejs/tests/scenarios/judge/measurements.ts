import { setTimeout as sleep } from 'timers/promises'
import { z } from 'zod'

import { internalFetch } from '~/common/utils/request'

import type { Named } from '../cards'
import type { Definition } from '../cards/definitions'
import { deliveryKey } from './invariants'
import type { JudgeEvidence } from './invariants'

export type MetricSample = { role: string; at: number; startedAt: number; cpuSeconds: number; rssBytes: number }

export type Measurement = { name: string; key?: string; value: number; unit: string }

export type MeasureEvidence = JudgeEvidence & { samples: readonly MetricSample[]; sampledFrom: number }

export type MeasurementDefinition = Definition & {
    unit: string
    measure(evidence: MeasureEvidence): { key?: string; value: number }[]
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

export const roleCpuSeconds: MeasurementDefinition = {
    name: 'role_cpu_seconds',
    params: z.object({}).strict(),
    unit: 's',
    measure: ({ samples, sampledFrom }) =>
        [...byRole(samples)].map(([role, ofRole]) => ({
            key: role,
            value: [...Map.groupBy(ofRole, ({ startedAt }) => startedAt)].reduce((sum, [startedAt, lifetime]) => {
                const startedWhileSampled = startedAt * 1000 >= sampledFrom
                return sum + lifetime.at(-1)!.cpuSeconds - (startedWhileSampled ? 0 : lifetime[0].cpuSeconds)
            }, 0),
        })),
}

export const roleRssMaxBytes: MeasurementDefinition = {
    name: 'role_rss_max_bytes',
    params: z.object({}).strict(),
    unit: 'bytes',
    measure: ({ samples }) =>
        [...byRole(samples)].map(([role, ofRole]) => ({
            key: role,
            value: Math.max(...ofRole.map(({ rssBytes }) => rssBytes)),
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

export const MEASUREMENTS: MeasurementDefinition[] = [roleCpuSeconds, roleRssMaxBytes, deliveryLatencyMs]

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

export function sampleOf(role: string, at: number, text: string): MetricSample | undefined {
    const startedAt = gauge(text, 'process_start_time_seconds')
    const cpuSeconds = gauge(text, 'process_cpu_seconds_total')
    const rssBytes = gauge(text, 'process_resident_memory_bytes')
    return startedAt === undefined || cpuSeconds === undefined || rssBytes === undefined
        ? undefined
        : { role, at, startedAt, cpuSeconds, rssBytes }
}

export type Sampler = { sampledFrom: number; stop(): Promise<MetricSample[]> }

type Target = { role: string; metricsUrl: string }

export async function startSampler(
    targets: Target[],
    { baselineWithinMs = BASELINE_WITHIN_MS } = {}
): Promise<Sampler> {
    const samples: MetricSample[] = []
    const stopped = new AbortController()
    const scrape = async (some: Target[]): Promise<void> => {
        await Promise.all(
            some.map(async ({ role, metricsUrl }) => {
                const at = Date.now()
                const text = await internalFetch(metricsUrl, { timeoutMs: SCRAPE_TIMEOUT_MS })
                    .then((response) => (response.status === 200 ? response.text() : ''))
                    .catch(() => '')
                const sample = sampleOf(role, at, text)
                if (sample) {
                    samples.push(sample)
                }
            })
        )
    }
    const scrapeAll = (): Promise<void> => scrape(targets)
    const sampledFrom = Date.now()
    let missing = targets
    for (;;) {
        await scrape(missing)
        missing = targets.filter(({ role }) => !samples.some((sample) => sample.role === role))
        if (missing.length === 0) {
            break
        }
        if (Date.now() + BASELINE_RETRY_MS > sampledFrom + baselineWithinMs) {
            throw new Error(
                `No metrics baseline from ${missing.map(({ role }) => role).join(', ')} within ${baselineWithinMs} ms`
            )
        }
        await sleep(BASELINE_RETRY_MS)
    }
    const sampling = (async () => {
        while (!stopped.signal.aborted) {
            await sleep(SAMPLE_INTERVAL_MS, undefined, { signal: stopped.signal }).catch(() => undefined)
            if (!stopped.signal.aborted) {
                await scrapeAll()
            }
        }
    })()
    let stopping: Promise<MetricSample[]> | undefined
    return {
        sampledFrom,
        stop: () =>
            (stopping ??= (async () => {
                stopped.abort()
                await sampling
                await scrapeAll()
                return samples
            })()),
    }
}
