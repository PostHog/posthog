import http from 'http'
import { AddressInfo } from 'net'
import { Registry, collectDefaultMetrics } from 'prom-client'

import type { TruthRecord } from '../provider-edge'
import type { JournalEntry } from './judge'
import { MeasureEvidence, Measurement, MetricSample, MissedScrape, measure, startSampler } from './measurements'

const FROM = Date.parse('2026-01-05T10:00:00.000Z')
const ROLE = 'cdp-cyclotron-worker-email'
const METRICS = 'process_start_time_seconds 1\nprocess_cpu_seconds_total 1\nprocess_resident_memory_bytes 1'

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
    missed: [],
    sampledFrom: FROM,
    ...partial,
})

describe('measurements', () => {
    const missedAt = (atS: number): MissedScrape => ({ role: ROLE, at: FROM + atS * 1000 })

    it.each<[string, MetricSample[], MissedScrape[], Pick<Measurement, 'value' | 'incomplete'>]>([
        ['one process across the run', [sample(0, -60, 10), sample(5, -60, 12), sample(10, -60, 15)], [], { value: 5 }],
        [
            'a process killed and started again, marked incomplete for the CPU after its last sample',
            [sample(0, -60, 10), sample(5, -60, 12), sample(10, 7, 1.5), sample(15, 7, 3)],
            [],
            { value: 5, incomplete: true },
        ],
        [
            'a process that missed a scrape and answered the next one',
            [sample(0, -60, 10), sample(10, -60, 15)],
            [missedAt(5)],
            { value: 5 },
        ],
        [
            'one process, while another role missed its last scrape',
            [sample(0, -60, 10), sample(5, -60, 12), sample(10, -60, 15)],
            [{ role: 'cdp-api', at: FROM + 15_000 }],
            { value: 5 },
        ],
        [
            'a process killed while its scrape was missed, marked incomplete',
            [sample(0, -60, 10), sample(5, -60, 12), sample(15, 12, 1.5)],
            [missedAt(10)],
            { value: 3.5, incomplete: true },
        ],
    ])('counts role_cpu_seconds per process lifetime for %s', (_story, samples, missed, measured) => {
        expect(measure([{ name: 'role_cpu_seconds', params: {} }], evidence({ samples, missed }))).toEqual([
            { name: 'role_cpu_seconds', key: ROLE, unit: 's', ...measured },
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

    it('samples the process metrics a role serves at start and at stop', async () => {
        const registry = new Registry()
        collectDefaultMetrics({ register: registry })
        const server = http.createServer(async (_req, res) => res.end(await registry.metrics()))
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        const { port } = server.address() as AddressInfo
        try {
            const sampler = await startSampler([{ role: ROLE, metricsUrl: `http://127.0.0.1:${port}/_metrics` }])
            const { samples } = await sampler.stop()

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

    it.each<[string, (scrape: number) => boolean, number, Pick<Measurement, 'incomplete'>]>([
        ['a role that answers at once', () => true, 5, {}],
        ['a role whose first scrape failed', (scrape) => scrape > 0, 5, {}],
        ['a role whose last scrape failed', (scrape) => scrape === 0, 0, { incomplete: true }],
    ])('measures %s from the baseline taken before it hands back', async (_story, answers, cpuUsed, marked) => {
        let cpuSeconds = 10
        let scrapes = 0
        const server = http.createServer((_req, res) => {
            if (!answers(scrapes++)) {
                res.writeHead(503).end()
                return
            }
            res.end(
                [
                    'process_start_time_seconds 1700000000',
                    `process_cpu_seconds_total ${cpuSeconds}`,
                    'process_resident_memory_bytes 100',
                ].join('\n')
            )
        })
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        const { port } = server.address() as AddressInfo
        try {
            const sampler = await startSampler([{ role: ROLE, metricsUrl: `http://127.0.0.1:${port}/_metrics` }])
            cpuSeconds = 15
            const sampled = await sampler.stop()

            expect(
                measure(
                    [
                        { name: 'role_cpu_seconds', params: {} },
                        { name: 'role_rss_max_bytes', params: {} },
                    ],
                    evidence({ ...sampled, sampledFrom: sampler.sampledFrom })
                )
            ).toEqual([
                { name: 'role_cpu_seconds', key: ROLE, unit: 's', value: cpuUsed, ...marked },
                { name: 'role_rss_max_bytes', key: ROLE, unit: 'bytes', value: 100, ...marked },
            ])
        } finally {
            server.closeAllConnections()
            await new Promise<void>((resolve) => server.close(() => resolve()))
        }
    })

    it.each<[string, (request: http.IncomingMessage, response: http.ServerResponse) => void]>([
        ['refuses the scrape', (_request, response) => response.writeHead(503).end()],
        [
            'answers the scrape only after the budget',
            (_request, response) => setTimeout(() => response.end(METRICS), 1500).unref(),
        ],
    ])('refuses to start within its budget, naming only the role that %s', async (_story, silent) => {
        const server = http.createServer((request, response) =>
            request.url === '/answering' ? response.end(METRICS) : silent(request, response)
        )
        await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve))
        const url = `http://127.0.0.1:${(server.address() as AddressInfo).port}`
        try {
            await expect(
                startSampler(
                    [
                        { role: ROLE, metricsUrl: `${url}/answering` },
                        { role: 'cdp-api', metricsUrl: `${url}/silent` },
                    ],
                    { baselineWithinMs: 1000 }
                )
            ).rejects.toThrow(/^No metrics baseline from cdp-api within 1000 ms$/)
        } finally {
            server.closeAllConnections()
            await new Promise<void>((resolve) => server.close(() => resolve()))
        }
    })
})
