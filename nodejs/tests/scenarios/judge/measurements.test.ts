import http from 'http'
import { AddressInfo } from 'net'
import { Registry, collectDefaultMetrics } from 'prom-client'

import type { WriterSample } from '../probe/writer-probe'
import type { TruthRecord } from '../provider-edge'
import type { ValveTimelineEntry } from '../valves/valves'
import type { JournalEntry } from './judge'
import {
    HostSample,
    MeasureEvidence,
    Measurement,
    MetricSample,
    MissedScrape,
    QueueSample,
    baselineOf,
    measure,
    sampleOf,
    startSampler,
} from './measurements'

const FROM = Date.parse('2026-01-05T10:00:00.000Z')
const ROLE = 'cdp-cyclotron-worker-email'
const METRICS = 'process_start_time_seconds 1\nprocess_cpu_seconds_total 1\nprocess_resident_memory_bytes 1'

const sample = (atS: number, startedAtS: number, cpuSeconds: number, rssBytes = 100, replica = 0): MetricSample => ({
    role: ROLE,
    replica,
    at: FROM + atS * 1000,
    startedAt: FROM / 1000 + startedAtS,
    cpuSeconds,
    rssBytes,
    processed: {},
    pgClientErrors: 0,
    consumerLoopErrors: 0,
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
    fetchRetries: 3,
    samples: [],
    missed: [],
    host: [],
    writer: [],
    queue: [],
    sampledFrom: FROM,
    drive: { startedAt: FROM, endedAt: FROM + 60_000 },
    timeline: [],
    ...partial,
})

const atS = (second: number): number => FROM + second * 1000
const isoAt = (second: number): string => new Date(atS(second)).toISOString()

const DRIVE = { startedAt: atS(0), endedAt: atS(1500) }
const VALVE: ValveTimelineEntry = {
    valve: 'role.kill',
    target: ROLE,
    requestedAt: isoAt(0),
    intentAt: isoAt(700),
    appliedAt: isoAt(700),
    observedAt: isoAt(700),
    releasedAt: isoAt(1100),
}

const everySecondOf = (fromS: number, toS: number, step = 1): number[] =>
    Array.from({ length: Math.floor((toS - fromS) / step) + 1 }, (_, i) => fromS + i * step)

const probedWriter = (failing: (second: number) => boolean, toS = 1500): WriterSample[] =>
    everySecondOf(0, toS).map((second) => ({
        at: atS(second),
        monoMs: second * 1000,
        latencyMs: 0,
        ...(failing(second) ? { ok: false, sqlstate: '57P01' } : { ok: true, inRecovery: false }),
    }))

const QUIET = { due: 2, oldestDueSeconds: 1 }
const BACKED_UP = { due: 50, oldestDueSeconds: 30 }

const probedQueue = (lag: (second: number) => typeof QUIET): QueueSample[] =>
    everySecondOf(0, 1500, 5).map((second) => ({
        at: atS(second),
        running: 1,
        created: (second + 5) / 2,
        ...lag(second),
    }))

const between = (fromS: number, toS: number) => (second: number) => second >= fromS && second <= toS

describe('measurements', () => {
    const missedAt = (atS: number, replica = 0): MissedScrape => ({ role: ROLE, replica, at: FROM + atS * 1000 })

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
            [{ role: 'cdp-api', replica: 0, at: FROM + 15_000 }],
            { value: 5 },
        ],
        [
            'a process killed while its scrape was missed, marked incomplete',
            [sample(0, -60, 10), sample(5, -60, 12), sample(15, 12, 1.5)],
            [missedAt(10)],
            { value: 3.5, incomplete: true },
        ],
        [
            'two replicas that started at the same instant, summed',
            [sample(0, -60, 10), sample(10, -60, 15), sample(0, -60, 20, 100, 1), sample(10, -60, 22, 100, 1)],
            [],
            { value: 7 },
        ],
        [
            'two replicas, one of which missed its last scrape, marked incomplete',
            [sample(0, -60, 10), sample(10, -60, 15), sample(0, -60, 20, 100, 1), sample(5, -60, 22, 100, 1)],
            [missedAt(10, 1)],
            { value: 7, incomplete: true },
        ],
    ])('counts role_cpu_seconds per process lifetime for %s', (_story, samples, missed, measured) => {
        expect(measure([{ name: 'role_cpu_seconds', params: {} }], evidence({ samples, missed }))).toEqual([
            { name: 'role_cpu_seconds', key: ROLE, unit: 's', ...measured },
        ])
    })

    it('keeps the largest resident set of each role across its replicas', () => {
        const samples = [sample(0, -60, 1, 300), sample(5, -60, 1, 900, 1), sample(10, 7, 1, 200)]

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
            const procStat = ['cpu  100 0 50 800 50 0 0 0 0 0', 'cpu  400 0 150 1300 150 0 0 0 0 0']
            const sampler = await startSampler(
                [{ role: ROLE, replica: 0, metricsUrl: `http://127.0.0.1:${port}/_metrics` }],
                { readHostStat: () => procStat.shift() ?? 'cpu  oops' }
            )
            const { samples, host } = await sampler.stop()

            expect(samples.map(({ role }) => role)).toEqual([ROLE, ROLE])
            expect(samples.at(-1)).toEqual({
                role: ROLE,
                replica: 0,
                at: expect.any(Number),
                startedAt: expect.any(Number),
                cpuSeconds: expect.any(Number),
                rssBytes: expect.any(Number),
                processed: {},
                pgClientErrors: 0,
                consumerLoopErrors: 0,
            })
            expect(samples.at(-1)!.rssBytes).toBeGreaterThan(0)
            expect(host).toEqual<HostSample[]>([
                { at: expect.any(Number), busyTicks: 150, totalTicks: 1000 },
                { at: expect.any(Number), busyTicks: 550, totalTicks: 2000 },
            ])
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
            const sampler = await startSampler([
                { role: ROLE, replica: 0, metricsUrl: `http://127.0.0.1:${port}/_metrics` },
            ])
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
                        { role: ROLE, replica: 0, metricsUrl: `${url}/answering` },
                        { role: ROLE, replica: 1, metricsUrl: `${url}/silent` },
                    ],
                    { baselineWithinMs: 1000 }
                )
            ).rejects.toThrow(new RegExp(`^No metrics baseline from ${ROLE}-1 within 1000 ms$`))
        } finally {
            server.closeAllConnections()
            await new Promise<void>((resolve) => server.close(() => resolve()))
        }
    })

    it.each<[string, string[], Pick<MetricSample, 'processed' | 'pgClientErrors' | 'consumerLoopErrors'>]>([
        [
            'a worker with Cyclotron claims on two queues and errors in two pools',
            [
                'cdp_cyclotron_jobs_processed{queue="email",source="postgres-v2"} 7',
                'cdp_cyclotron_jobs_processed{queue="hogflow",source="postgres-v2"} 3',
                'cdp_cyclotron_jobs_processed{queue="hogflow",source="kafka"} 100',
                'cdp_cyclotron_v2_pg_client_errors_total{pool="worker"} 2',
                'cdp_cyclotron_v2_pg_client_errors_total{pool="janitor"} 1',
                'cdp_cyclotron_v2_consumer_loop_errors_total{queue="email"} 4',
            ],
            { processed: { email: 7, hogflow: 3 }, pgClientErrors: 3, consumerLoopErrors: 4 },
        ],
        ['a role whose labelled counters never moved', [], { processed: {}, pgClientErrors: 0, consumerLoopErrors: 0 }],
    ])('samples the Cyclotron counters of %s', (_story, lines, counters) => {
        const text = [METRICS, '# HELP cdp_cyclotron_jobs_processed The number of jobs', ...lines].join('\n')

        expect(sampleOf({ role: ROLE, replica: 0, metricsUrl: '' }, FROM, text)).toEqual({
            role: ROLE,
            replica: 0,
            at: FROM,
            startedAt: 1,
            cpuSeconds: 1,
            rssBytes: 1,
            ...counters,
        })
    })

    it.each<[string, string, (second: number) => boolean, ValveTimelineEntry[], Omit<Measurement, 'name' | 'unit'>[]]>([
        [
            'sums the failed intervals of the valve phase, each from the last commit to the next',
            'writer_unavailable_seconds',
            (second) => between(710, 714)(second) || between(750, 751)(second) || between(1200, 1210)(second),
            [VALVE],
            [{ value: 9 }],
        ],
        [
            'counts an interval cut short by the end of the valve phase as censored',
            'writer_unavailable_seconds',
            between(1095, 1105),
            [VALVE],
            [{ value: 6, censored: true }],
        ],
        ['measures nothing for a card without a valve', 'writer_unavailable_seconds', between(710, 714), [], []],
        [
            'sums the failed intervals of the fail-back phase, censored at drive end',
            'failback_writer_unavailable_seconds',
            (second) => between(1200, 1201)(second) || second >= 1490,
            [VALVE],
            [{ value: 14, censored: true }],
        ],
        [
            'times the first commit after the first failure from the start of the valve phase',
            'seconds_to_first_probe_commit',
            (second) => between(710, 714)(second) || between(750, 751)(second),
            [VALVE],
            [{ value: 15 }],
        ],
        [
            'reads no failure in the valve phase as no wait for a commit',
            'seconds_to_first_probe_commit',
            () => false,
            [VALVE],
            [{ value: 0 }],
        ],
    ])('%s', (_story, name, failing, timeline, measured) => {
        const writer = probedWriter(failing)

        expect(measure([{ name, params: {} }], evidence({ writer, drive: DRIVE, timeline }))).toEqual(
            measured.map((value) => ({ name, unit: 's', ...value }))
        )
    })

    const SPIKE_BEFORE_THE_ENVELOPE = (second: number): typeof QUIET =>
        second === 50 ? { due: 99, oldestDueSeconds: 99 } : QUIET

    it.each<[string, string, (second: number) => typeof QUIET, Omit<Measurement, 'name' | 'unit'>[]]>([
        [
            'drains once both lag series stay inside the last ten baseline minutes for a minute',
            'drain_seconds',
            (second) => (between(720, 760)(second) || second === 790 ? BACKED_UP : SPIKE_BEFORE_THE_ENVELOPE(second)),
            [{ value: 95 }],
        ],
        [
            'drains at once when the lag never leaves the envelope',
            'drain_seconds',
            SPIKE_BEFORE_THE_ENVELOPE,
            [{ value: 0 }],
        ],
        [
            'censors a drain the valve phase ends before',
            'drain_seconds',
            (second) => (between(1050, 1100)(second) ? BACKED_UP : QUIET),
            [{ value: null, censored: true }],
        ],
        [
            'drains the fail-back phase against the same envelope',
            'failback_drain_seconds',
            (second) => (between(1110, 1200)(second) ? BACKED_UP : QUIET),
            [{ value: 105 }],
        ],
        [
            'peaks the oldest due age inside the valve phase only',
            'queue_lag_peak_seconds',
            (second) =>
                between(720, 760)(second) ? BACKED_UP : second === 1200 ? { due: 1, oldestDueSeconds: 500 } : QUIET,
            [{ value: 30 }],
        ],
    ])('%s', (_story, name, lag, measured) => {
        const queue = [...probedQueue(lag), { at: atS(902), error: 'Postgres at db failed: timeout' }]

        expect(measure([{ name, params: {} }], evidence({ queue, drive: DRIVE, timeline: [VALVE] }))).toEqual(
            measured.map((value) => ({ name, unit: 's', ...value }))
        )
    })

    it('counts Cyclotron errors over the valve phase across a restart, summed over replicas', () => {
        const errors = (
            atSecond: number,
            startedAtS: number,
            pgClientErrors: number,
            consumerLoopErrors: number,
            replica = 0
        ): MetricSample => ({ ...sample(atSecond, startedAtS, 1, 100, replica), pgClientErrors, consumerLoopErrors })
        const samples = [
            errors(650, -60, 5, 1),
            errors(750, -60, 8, 1),
            errors(800, 760, 2, 3),
            errors(1050, 760, 4, 3),
            errors(1150, 760, 10, 9),
            errors(650, -60, 0, 0, 1),
            errors(1050, -60, 1, 2, 1),
        ]

        expect(
            measure(
                [
                    { name: 'pg_client_errors', params: {} },
                    { name: 'consumer_loop_errors', params: {} },
                ],
                evidence({ samples, drive: DRIVE, timeline: [VALVE] })
            )
        ).toEqual([
            { name: 'pg_client_errors', unit: 'errors', value: 8 },
            { name: 'consumer_loop_errors', unit: 'errors', value: 5 },
        ])
    })

    it('rates the baseline claims per queue, new jobs and host CPU from the drive start to the valve intent', () => {
        const claims = (atSecond: number, processed: Record<string, number>, replica = 0): MetricSample => ({
            ...sample(atSecond, -60, 1, 100, replica),
            processed,
        })
        const samples = [
            claims(0, {}),
            claims(600, { email: 150, hogflow: 75 }),
            claims(800, { email: 9000, hogflow: 9000 }),
            claims(-50, { email: 10 }, 1),
            claims(550, { email: 85 }, 1),
        ]
        const host: HostSample[] = [
            { at: atS(-5), busyTicks: 1000, totalTicks: 10_000 },
            { at: atS(695), busyTicks: 3800, totalTicks: 17_000 },
            { at: atS(800), busyTicks: 17_000, totalTicks: 17_100 },
        ]
        const recorded = evidence({ samples, host, queue: probedQueue(() => QUIET), drive: DRIVE, timeline: [VALVE] })

        expect({
            baseline: baselineOf(recorded),
            measured: measure(
                [
                    { name: 'baseline_claims_per_second', params: {} },
                    { name: 'baseline_new_jobs_per_second', params: {} },
                ],
                recorded
            ),
        }).toEqual({
            baseline: {
                seconds: 700,
                claimsPerSecond: { email: 0.375, hogflow: 0.125 },
                newJobsPerSecond: 0.5,
                hostBusyShare: 0.4,
            },
            measured: [
                { name: 'baseline_claims_per_second', key: 'email', unit: 'jobs/s', value: 0.375 },
                { name: 'baseline_claims_per_second', key: 'hogflow', unit: 'jobs/s', value: 0.125 },
                { name: 'baseline_new_jobs_per_second', unit: 'jobs/s', value: 0.5 },
            ],
        })
    })
})
