import http from 'http'
import { AddressInfo } from 'net'
import { Registry, collectDefaultMetrics } from 'prom-client'

import type { TruthRecord } from '../provider-edge'
import type { JournalEntry } from './judge'
import { MeasureEvidence, MetricSample, measure, startSampler } from './measurements'

const FROM = Date.parse('2026-01-05T10:00:00.000Z')
const ROLE = 'cdp-cyclotron-worker-email'

const sample = (atS: number, startedAtS: number, cpuSeconds: number, rssBytes = 100): MetricSample => ({
    role: ROLE,
    at: FROM + atS * 1000,
    startedAt: FROM / 1000 + startedAtS,
    cpuSeconds,
    rssBytes,
})

const offered = (unitId: string, offeredAtMs: number): JournalEntry => ({
    unitId,
    kind: 'event',
    teamId: 7,
    offeredAt: FROM + offeredAtMs,
    answer: { accepted: true },
    expect: { deliveries: ['email'] },
})

const record = (seq: number, unitId: string, atMs: number, status = 200): TruthRecord => ({
    seq,
    at: new Date(FROM + atMs).toISOString(),
    kind: 'ses.send',
    unitId,
    actionId: 'email',
    status,
    detail: {},
})

const evidence = (partial: Partial<MeasureEvidence>): MeasureEvidence => ({
    journal: [],
    truth: [],
    samples: [],
    sampledFrom: FROM,
    ...partial,
})

describe('measurements', () => {
    it.each<[string, MetricSample[], number]>([
        ['one process across the run', [sample(0, -60, 10), sample(5, -60, 12), sample(10, -60, 15)], 5],
        [
            'a process killed and started again',
            [sample(0, -60, 10), sample(5, -60, 12), sample(10, 7, 1.5), sample(15, 7, 3)],
            5,
        ],
    ])('counts role_cpu_seconds per process lifetime for %s', (_story, samples, cpuSeconds) => {
        expect(measure([{ name: 'role_cpu_seconds', params: {} }], evidence({ samples }))).toEqual([
            { name: 'role_cpu_seconds', key: ROLE, value: cpuSeconds, unit: 's' },
        ])
    })

    it('keeps the largest resident set of each role', () => {
        const samples = [sample(0, -60, 1, 300), sample(5, -60, 1, 900), sample(10, 7, 1, 200)]

        expect(measure([{ name: 'role_rss_max_bytes', params: {} }], evidence({ samples }))).toEqual([
            { name: 'role_rss_max_bytes', key: ROLE, value: 900, unit: 'bytes' },
        ])
    })

    it('times each delivery from its offer to its first accepted send, skipping refused and undelivered units', () => {
        const latencies = Array.from({ length: 20 }, (_, i) => (i + 1) * 100)
        const journal = [
            ...latencies.map((_, i) => offered(`run-a-${i + 1}`, 0)),
            { ...offered('run-a-refused', 0), answer: { accepted: false as const, status: 503 } },
            offered('run-a-lost', 0),
        ]
        const truth = [
            record(1, 'run-a-1', 50, 503),
            ...latencies.map((latency, i) => record(i + 2, `run-a-${i + 1}`, latency)),
            record(30, 'run-a-20', 9000),
            record(31, 'run-a-refused', 10),
        ]

        expect(measure([{ name: 'delivery_latency_ms', params: {} }], evidence({ journal, truth }))).toEqual([
            { name: 'delivery_latency_ms', key: 'p50', value: 1000, unit: 'ms' },
            { name: 'delivery_latency_ms', key: 'p95', value: 1900, unit: 'ms' },
            { name: 'delivery_latency_ms', key: 'max', value: 2000, unit: 'ms' },
        ])
    })

    it('samples the process metrics a role serves at start and at stop, skipping a role that does not answer', async () => {
        const registry = new Registry()
        collectDefaultMetrics({ register: registry })
        const server = http.createServer(async (_req, res) => res.end(await registry.metrics()))
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        const { port } = server.address() as AddressInfo
        try {
            const sampler = startSampler(
                [
                    { role: ROLE, metricsUrl: `http://127.0.0.1:${port}/_metrics` },
                    { role: 'cdp-api', metricsUrl: 'http://127.0.0.1:1/_metrics' },
                ],
                60_000
            )
            const samples = await sampler.stop()

            expect(samples.map(({ role }) => role)).toEqual([ROLE, ROLE])
            expect(samples.at(-1)).toEqual({
                role: ROLE,
                at: expect.any(Number),
                startedAt: expect.any(Number),
                cpuSeconds: expect.any(Number),
                rssBytes: expect.any(Number),
            })
            expect(samples.at(-1)!.rssBytes).toBeGreaterThan(0)
        } finally {
            server.closeAllConnections()
            await new Promise<void>((resolve) => server.close(() => resolve()))
        }
    })
})
