import http from 'http'
import { AddressInfo } from 'net'
import { Registry, collectDefaultMetrics } from 'prom-client'

import type { WriterSample } from '../probe/writer-probe'
import type { TruthRecord } from '../provider-edge'
import type { ValveTimelineEntry } from '../valves/valves'
import type { JournalEntry } from './judge'
import {
    DriveWindow,
    HostSample,
    MeasureEvidence,
    Measurement,
    MetricSample,
    MissedScrape,
    QueueSample,
    baselineOf,
    janitorResetsOf,
    measure,
    phasesOf,
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
    janitorStalled: 0,
    lateness: {},
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
    steps: [],
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

const FAILOVER: ValveTimelineEntry = {
    ...VALVE,
    valve: 'pg.failover',
    target: 'cyclotron',
    observations: [
        { name: 'cluster_writer', at: isoAt(720) },
        { name: 'first_probe_commit', at: isoAt(740) },
    ],
}

const everySecondOf = (fromS: number, toS: number, step = 1): number[] =>
    Array.from({ length: Math.floor((toS - fromS) / step) + 1 }, (_, i) => fromS + i * step)

type Attempt = boolean | 'skipped' | { failedAfterMs: number }

const probedWriter = (failing: (second: number) => Attempt, toS = 1500): WriterSample[] =>
    everySecondOf(0, toS).flatMap((second): WriterSample[] => {
        const attempt = failing(second)
        if (attempt === 'skipped') {
            return []
        }
        const at = { at: atS(second), monoMs: second * 1000 }
        return attempt === false
            ? [{ ...at, latencyMs: 0, ok: true, inRecovery: false }]
            : [{ ...at, latencyMs: attempt === true ? 0 : attempt.failedAfterMs, ok: false, sqlstate: '57P01' }]
    })

const QUIET = { due: 2, oldestDueSeconds: 1 }
const BACKED_UP = { due: 50, oldestDueSeconds: 30 }

type Read = typeof QUIET | 'failed' | 'missed'

const probedQueue = (lag: (second: number) => Read, step = 5): QueueSample[] =>
    everySecondOf(0, 1500, step).flatMap((second): QueueSample[] => {
        const read = lag(second)
        return read === 'missed'
            ? []
            : read === 'failed'
              ? [{ at: atS(second), error: 'Postgres at db failed: timeout' }]
              : [{ at: atS(second), running: 1, inserted: (second + 5) / 2, ...read }]
    })

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

    it.each([
        ['a few scrapes', [sample(0, -60, 1, 300), sample(5, -60, 1, 900, 1), sample(10, 7, 1, 200)]],
        [
            'more scrapes than one call takes arguments',
            Array.from({ length: 200_000 }, (_, i) => sample(i * 5, -60, 1, i === 1234 ? 900 : 300)),
        ],
    ])('keeps the largest resident set of each role across its replicas over %s', (_story, samples) => {
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
            const procStat = ['cpu  100 0 50 800 50 0 0 0 40 0', 'cpu  400 20 130 1300 150 0 0 0 200 20']
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
                janitorStalled: 0,
                lateness: {},
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

    it.each<
        [
            string,
            string[],
            Pick<MetricSample, 'processed' | 'pgClientErrors' | 'consumerLoopErrors' | 'janitorStalled' | 'lateness'>,
        ]
    >([
        [
            'a worker with Cyclotron claims on two queues, errors in two pools and pickups of both waits',
            [
                'cdp_cyclotron_jobs_processed{queue="email",source="postgres-v2"} 7',
                'cdp_cyclotron_jobs_processed{queue="hogflow",source="postgres-v2"} 3',
                'cdp_cyclotron_jobs_processed{queue="hogflow",source="kafka"} 100',
                'cdp_cyclotron_v2_pg_client_errors_total{pool="worker"} 2',
                'cdp_cyclotron_v2_pg_client_errors_total{pool="janitor"} 1',
                'cdp_cyclotron_v2_consumer_loop_errors_total{queue="email"} 4',
                'cdp_cyclotron_v2_janitor_stalled 5',
                'cdp_cyclotron_job_lateness_seconds_bucket{le="5",queue="email",wait="scheduled"} 6',
                'cdp_cyclotron_job_lateness_seconds_bucket{le="+Inf",queue="email",wait="scheduled"} 7',
                'cdp_cyclotron_job_lateness_seconds_bucket{le="5",queue="email",wait="deferred"} 1',
                'cdp_cyclotron_job_lateness_seconds_bucket{le="+Inf",queue="email",wait="deferred"} 2',
                'cdp_cyclotron_job_lateness_seconds_count{queue="email",wait="scheduled"} 7',
            ],
            {
                processed: { email: 7, hogflow: 3 },
                pgClientErrors: 3,
                consumerLoopErrors: 4,
                janitorStalled: 5,
                lateness: { email: { '5': 7, '+Inf': 9 } },
            },
        ],
        [
            'a role whose labelled counters never moved',
            [],
            { processed: {}, pgClientErrors: 0, consumerLoopErrors: 0, janitorStalled: 0, lateness: {} },
        ],
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

    it.each<[string, string, (second: number) => Attempt, ValveTimelineEntry[], Omit<Measurement, 'name' | 'unit'>[]]>([
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
            'waits for a commit after a write that started before the valve and failed inside it',
            'seconds_to_first_probe_commit',
            (second) => (second === 699 ? { failedAfterMs: 1500 } : second === 700 ? 'skipped' : false),
            [VALVE],
            [{ value: 1 }],
        ],
        [
            'times each recovery stage the failover observed from its intent',
            'seconds_to_cluster_writer',
            () => false,
            [FAILOVER],
            [{ value: 20 }],
        ],
        [
            'times the first probe commit on the promoted writer, not the first commit after a failure',
            'seconds_to_first_probe_commit',
            between(710, 714),
            [FAILOVER],
            [{ value: 40 }],
        ],
        [
            'times the first commit from the valve inside the drive, not from a failover applied after it ended',
            'seconds_to_first_probe_commit',
            (second) => between(710, 714)(second) || between(750, 751)(second),
            [VALVE, { ...FAILOVER, intentAt: isoAt(1600) }],
            [{ value: 15 }],
        ],
        [
            'censors a recovery stage the failover never observed',
            'seconds_to_sql_writer',
            () => false,
            [FAILOVER],
            [{ value: null, censored: true }],
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

    type Latency = number | 'failed' | { failedAfterMs: number }

    const latencyWriter = (latency: (second: number) => Latency): WriterSample[] =>
        everySecondOf(0, 1500).map((second): WriterSample => {
            const ms = latency(second)
            const at = { at: atS(second), monoMs: second * 1000 }
            return ms === 'failed'
                ? { ...at, latencyMs: 0, ok: false, sqlstate: '57P01' }
                : typeof ms === 'object'
                  ? { ...at, latencyMs: ms.failedAfterMs, ok: false, sqlstate: '57014' }
                  : { ...at, latencyMs: ms, ok: true, inRecovery: false }
        })

    const THREE_MINUTE_VALVE: ValveTimelineEntry[] = [{ ...VALVE, releasedAt: isoAt(880) }]

    it.each<
        [
            string,
            (second: number) => Latency,
            ValveTimelineEntry[],
            Omit<Measurement, 'name' | 'unit'>[],
            ((second: number) => boolean)?,
        ]
    >([
        [
            'recovers at the first minute from which every later minute stays at or under twice the baseline p99',
            (second) => (between(700, 759)(second) ? 400 : between(760, 819)(second) ? 30 : second >= 820 ? 15 : 10),
            THREE_MINUTE_VALVE,
            [
                { key: 'baseline', value: 10 },
                { key: 'bar', value: 20 },
                { key: 't0', value: 400 },
                { key: 't60', value: 30 },
                { key: 't120', value: 15 },
                { key: 'recovery_seconds', value: 120 },
            ],
        ],
        [
            'censors the recovery when a probe fails in the last minute, though its commits are fast',
            (second) => (between(840, 845)(second) ? 'failed' : 10),
            THREE_MINUTE_VALVE,
            [
                { key: 'baseline', value: 10 },
                { key: 'bar', value: 20 },
                { key: 't0', value: 10 },
                { key: 't60', value: 10 },
                { key: 't120', value: 10 },
                { key: 'recovery_seconds', value: null, censored: true },
            ],
        ],
        [
            'reads a minute with no commit as not recovered',
            (second) => (between(700, 759)(second) ? 'failed' : 10),
            THREE_MINUTE_VALVE,
            [
                { key: 'baseline', value: 10 },
                { key: 'bar', value: 20 },
                { key: 't0', value: null, censored: true },
                { key: 't60', value: 10 },
                { key: 't120', value: 10 },
                { key: 'recovery_seconds', value: 60 },
            ],
        ],
        [
            'marks a minute whose probes stop for over 10 seconds as incomplete and not recovered',
            (second) => (between(700, 759)(second) ? 400 : 10),
            THREE_MINUTE_VALVE,
            [
                { key: 'baseline', value: 10 },
                { key: 'bar', value: 20 },
                { key: 't0', value: 400 },
                { key: 't60', value: 10 },
                { key: 't120', value: 10, incomplete: true },
                { key: 'recovery_seconds', value: null, censored: true },
            ],
            (second) => !between(822, 879)(second),
        ],
        [
            'marks both minutes of a probe silence split by a minute boundary as incomplete and not recovered',
            () => 10,
            THREE_MINUTE_VALVE,
            [
                { key: 'baseline', value: 10 },
                { key: 'bar', value: 20 },
                { key: 't0', value: 10, incomplete: true },
                { key: 't60', value: 10, incomplete: true },
                { key: 't120', value: 10 },
                { key: 'recovery_seconds', value: 120 },
            ],
            (second) => !between(752, 768)(second),
        ],
        [
            'counts a probe that fails after a minute boundary in both minutes it overlaps',
            (second) => (between(700, 758)(second) ? 400 : second === 759 ? { failedAfterMs: 2000 } : 10),
            THREE_MINUTE_VALVE,
            [
                { key: 'baseline', value: 10 },
                { key: 'bar', value: 20 },
                { key: 't0', value: 400 },
                { key: 't60', value: 10 },
                { key: 't120', value: 10 },
                { key: 'recovery_seconds', value: 120 },
            ],
        ],
        [
            'keeps a probe that fails after T0 out of the baseline and counts it in the first valve minute',
            (second) => (second === 699 ? { failedAfterMs: 2000 } : 10),
            THREE_MINUTE_VALVE,
            [
                { key: 'baseline', value: 10 },
                { key: 'bar', value: 20 },
                { key: 't0', value: 10 },
                { key: 't60', value: 10 },
                { key: 't120', value: 10 },
                { key: 'recovery_seconds', value: 60 },
            ],
        ],
        [
            'folds a sub-second remainder into the last minute, so an empty remainder censors nothing',
            (second) => (between(700, 759)(second) ? 400 : 10),
            [{ ...VALVE, releasedAt: isoAt(880.5) }],
            [
                { key: 'baseline', value: 10 },
                { key: 'bar', value: 20 },
                { key: 't0', value: 400 },
                { key: 't60', value: 10 },
                { key: 't120', value: 10 },
                { key: 'recovery_seconds', value: 60 },
            ],
            (second) => second !== 880,
        ],
        [
            'reads a slow last minute as not recovered, though one fast probe lands in its sub-second remainder',
            (second) => (between(700, 879)(second) ? 400 : 10),
            [{ ...VALVE, releasedAt: isoAt(880.5) }],
            [
                { key: 'baseline', value: 10 },
                { key: 'bar', value: 20 },
                { key: 't0', value: 400 },
                { key: 't60', value: 400 },
                { key: 't120', value: 400 },
                { key: 'recovery_seconds', value: null, censored: true },
            ],
        ],
        [
            'keeps the minutes of a valve whose baseline had a failed probe, with no bar and no recovery',
            (second) => (second === 650 ? 'failed' : between(700, 759)(second) ? 400 : 10),
            THREE_MINUTE_VALVE,
            [
                { key: 'baseline', value: null, censored: true },
                { key: 'bar', value: null, censored: true },
                { key: 't0', value: 400 },
                { key: 't60', value: 10 },
                { key: 't120', value: 10 },
                { key: 'recovery_seconds', value: null, censored: true },
            ],
        ],
        ['measures nothing for a card without a valve', () => 10, [], []],
        ['measures nothing on a baseline under 30 seconds', () => 10, [{ ...VALVE, intentAt: isoAt(10) }], []],
    ])('write latency p99 %s', (_story, latency, timeline, measured, probed = () => true) => {
        const names = ['write_latency_p99_ms', 'write_latency_recovery_seconds']
        const recovery = measured.filter(({ key }) => key === 'recovery_seconds')

        expect(
            measure(
                names.map((name) => ({ name, params: {} })),
                evidence({
                    writer: latencyWriter(latency).filter(({ at }) => probed((at - FROM) / 1000)),
                    drive: DRIVE,
                    timeline,
                })
            )
        ).toEqual([
            ...measured
                .filter((value) => !recovery.includes(value))
                .map((value) => ({ name: names[0], unit: 'ms', ...value })),
            ...recovery.map(({ key: _key, ...value }) => ({ name: names[1], unit: 's', ...value })),
        ])
    })

    const HOGFLOW = 'cdp-cyclotron-worker-hogflow'

    const pickedEvery5s = (
        slow: (second: number) => boolean,
        { offsetS = 0, slowCount = 10, pastLargest = false } = {}
    ): MetricSample[] => {
        let fast = 0
        let late = 0
        let past = 0
        return everySecondOf(0, 1500 - offsetS, 5).map((start) => {
            const second = start + offsetS
            if (!slow(second)) {
                fast += 10
            } else if (pastLargest) {
                past += slowCount
            } else {
                late += slowCount
            }
            return {
                ...sample(second, 0, 1),
                role: HOGFLOW,
                lateness: { hogflow: { '0.5': fast, '5': fast + late, '+Inf': fast + late + past } },
            }
        })
    }

    const pickedWith = (
        picked: (second: number) => [fast: number, slow: number],
        { replica = 0, slowFrom = 0 } = {}
    ): MetricSample[] => {
        let fast = 0
        let slow = slowFrom
        return everySecondOf(2, 1497, 5).map((second) => {
            const [newFast, newSlow] = picked(second)
            fast += newFast
            slow += newSlow
            return {
                ...sample(second, 0, 1, 100, replica),
                role: HOGFLOW,
                lateness: { hogflow: { '0.5': fast, '5': fast + slow, '+Inf': fast + slow } },
            }
        })
    }
    const LAST_MINUTE_SCRAPES = between(822, 877)

    it.each<[string, MetricSample[], Omit<Measurement, 'name' | 'unit'>[]]>([
        [
            'reads a slow pickup in the last minute as not recovered, though fast pickups after the valve end share its closing interval',
            pickedWith((second) =>
                between(707, 757)(second)
                    ? [0, 10]
                    : second === 872
                      ? [0, 1]
                      : LAST_MINUTE_SCRAPES(second)
                        ? [0, 0]
                        : second === 882
                          ? [100, 0]
                          : [10, 0]
            ),
            [
                { key: 'hogflow_baseline', value: 0.5 },
                { key: 'hogflow_bar', value: 1 },
                { key: 'hogflow_t0', value: 5 },
                { key: 'hogflow_t60', value: 0.5 },
                { key: 'hogflow_t120', value: 5 },
                { key: 'hogflow_recovery_seconds', value: null, censored: true },
            ],
        ],
        [
            'reads 99 fast pickups of 101 in the last minute as not recovered when the closing interval could hold its second slow one',
            pickedWith((second) =>
                between(707, 757)(second)
                    ? [0, 10]
                    : second === 877
                      ? [0, 1]
                      : between(822, 872)(second)
                        ? [9, 0]
                        : second === 882
                          ? [100, 1]
                          : [10, 0]
            ),
            [
                { key: 'hogflow_baseline', value: 0.5 },
                { key: 'hogflow_bar', value: 1 },
                { key: 'hogflow_t0', value: 5 },
                { key: 'hogflow_t60', value: 0.5 },
                { key: 'hogflow_t120', value: 5 },
                { key: 'hogflow_recovery_seconds', value: null, censored: true },
            ],
        ],
        [
            'marks the last minute incomplete when a counter drops across the valve end with an unchanged start time',
            [
                ...pickedWith((second) => (between(872, 882)(second) ? [0, 0] : [10, 0])),
                ...pickedWith((second) => (between(822, 867)(second) ? [0, 1] : [0, 0]), {
                    replica: 1,
                    slowFrom: 100,
                }).map((scrape) =>
                    scrape.at >= atS(882)
                        ? { ...scrape, lateness: { hogflow: { '0.5': 0, '5': 99, '+Inf': 99 } } }
                        : scrape
                ),
            ],
            [
                { key: 'hogflow_baseline', value: 0.5 },
                { key: 'hogflow_bar', value: 1 },
                { key: 'hogflow_t0', value: 0.5 },
                { key: 'hogflow_t60', value: 0.5 },
                { key: 'hogflow_t120', value: 5, incomplete: true },
                { key: 'hogflow_recovery_seconds', value: null, censored: true },
            ],
        ],
        [
            'still recovers when every pickup in the closing interval is fast',
            pickedWith((second) => (between(707, 757)(second) ? [0, 10] : [10, 0])),
            [
                { key: 'hogflow_baseline', value: 0.5 },
                { key: 'hogflow_bar', value: 1 },
                { key: 'hogflow_t0', value: 5 },
                { key: 'hogflow_t60', value: 0.5 },
                { key: 'hogflow_t120', value: 0.5 },
                { key: 'hogflow_recovery_seconds', value: null, censored: true },
            ],
        ],
        [
            'recovers once every later minute of a queue stays at or under twice its baseline p99',
            pickedEvery5s(between(705, 760)),
            [
                { key: 'hogflow_baseline', value: 0.5 },
                { key: 'hogflow_bar', value: 1 },
                { key: 'hogflow_t0', value: 5 },
                { key: 'hogflow_t60', value: 0.5 },
                { key: 'hogflow_t120', value: 0.5 },
                { key: 'hogflow_recovery_seconds', value: null, censored: true },
            ],
        ],
        [
            'censors a queue still slow in the last minute',
            pickedEvery5s((second) => second >= 705),
            [
                { key: 'hogflow_baseline', value: 0.5 },
                { key: 'hogflow_bar', value: 1 },
                { key: 'hogflow_t0', value: 5 },
                { key: 'hogflow_t60', value: 5 },
                { key: 'hogflow_t120', value: 5 },
                { key: 'hogflow_recovery_seconds', value: null, censored: true },
            ],
        ],
        [
            'counts a scrape interval that straddles T0 after T0 only, so slow pickups after the fault leave the baseline alone',
            pickedEvery5s(between(702, 702), { offsetS: 2, slowCount: 50 }),
            [
                { key: 'hogflow_baseline', value: 0.5 },
                { key: 'hogflow_bar', value: 1 },
                { key: 'hogflow_t0', value: 5 },
                { key: 'hogflow_t60', value: 0.5 },
                { key: 'hogflow_t120', value: 0.5 },
                { key: 'hogflow_recovery_seconds', value: null, censored: true },
            ],
        ],
        [
            'counts the scrape interval that straddles the valve end in the last minute, so late pickups at its tail stay',
            pickedEvery5s((second) => between(705, 760)(second) || second === 882, { offsetS: 2, slowCount: 50 }),
            [
                { key: 'hogflow_baseline', value: 0.5 },
                { key: 'hogflow_bar', value: 1 },
                { key: 'hogflow_t0', value: 5 },
                { key: 'hogflow_t60', value: 0.5 },
                { key: 'hogflow_t120', value: 5 },
                { key: 'hogflow_recovery_seconds', value: null, censored: true },
            ],
        ],
        [
            'marks the last minute incomplete and not recovered when no scrape closes the valve end',
            pickedEvery5s(between(705, 760), { offsetS: 2 }).filter(({ at }) => at <= atS(877)),
            [
                { key: 'hogflow_baseline', value: 0.5 },
                { key: 'hogflow_bar', value: 1 },
                { key: 'hogflow_t0', value: 5 },
                { key: 'hogflow_t60', value: 0.5 },
                { key: 'hogflow_t120', value: 0.5, incomplete: true },
                { key: 'hogflow_recovery_seconds', value: null, censored: true },
            ],
        ],
        [
            'marks the last minute incomplete when the worker restarts before a scrape closes the valve end',
            [
                ...pickedEvery5s(between(705, 760), { offsetS: 2 }).filter(({ at }) => at <= atS(877)),
                {
                    ...sample(882, 881, 1),
                    role: HOGFLOW,
                    lateness: { hogflow: { '0.5': 10, '5': 10, '+Inf': 10 } },
                },
            ],
            [
                { key: 'hogflow_baseline', value: 0.5 },
                { key: 'hogflow_bar', value: 1 },
                { key: 'hogflow_t0', value: 5 },
                { key: 'hogflow_t60', value: 0.5 },
                { key: 'hogflow_t120', value: 0.5, incomplete: true },
                { key: 'hogflow_recovery_seconds', value: null, censored: true },
            ],
        ],
        [
            'censors a minute whose p99 is past the largest bucket',
            pickedEvery5s(between(705, 760), { pastLargest: true }),
            [
                { key: 'hogflow_baseline', value: 0.5 },
                { key: 'hogflow_bar', value: 1 },
                { key: 'hogflow_t0', value: 5, censored: true },
                { key: 'hogflow_t60', value: 0.5 },
                { key: 'hogflow_t120', value: 0.5 },
                { key: 'hogflow_recovery_seconds', value: null, censored: true },
            ],
        ],
        [
            'marks a minute whose worker went unscraped as incomplete and not recovered',
            pickedEvery5s(() => false).filter(({ at }) => at < atS(770) || at > atS(800)),
            [
                { key: 'hogflow_baseline', value: 0.5 },
                { key: 'hogflow_bar', value: 1 },
                { key: 'hogflow_t0', value: 0.5 },
                { key: 'hogflow_t60', value: null, censored: true, incomplete: true },
                { key: 'hogflow_t120', value: 0.5 },
                { key: 'hogflow_recovery_seconds', value: null, censored: true },
            ],
        ],
    ])('pickup p99 %s', (_story, samples, measured) => {
        const names = ['pickup_p99_seconds', 'pickup_recovery_seconds']
        const recovery = measured.filter(({ key }) => key?.endsWith('_recovery_seconds'))

        expect(
            measure(
                names.map((name) => ({ name, params: {} })),
                evidence({ samples, drive: DRIVE, timeline: THREE_MINUTE_VALVE })
            )
        ).toEqual([
            ...measured
                .filter((value) => !recovery.includes(value))
                .map((value) => ({ name: names[0], unit: 's', ...value })),
            ...recovery.map(({ key, ...value }) => ({
                name: names[1],
                unit: 's',
                key: key!.replace('_recovery_seconds', ''),
                ...value,
            })),
        ])
    })

    it('never reads the last minute pickup p99 under the p99 of any share of the closing pickups that falls inside it', () => {
        const p99Bound = ([fast, slow, past]: number[]): number => {
            const rank = Math.ceil(0.99 * (fast + slow + past))
            return rank <= fast ? 0.5 : rank <= fast + slow ? 5 : Infinity
        }
        const upTo = (count: number): number[] => Array.from({ length: count + 1 }, (_, i) => i)
        const combinations = (...choices: number[][]): number[][] =>
            choices.reduce<number[][]>((sets, options) => sets.flatMap((set) => options.map((n) => [...set, n])), [[]])
        for (const inside of combinations([0, 1, 98, 99, 100], [0, 1, 2], [0, 1])) {
            for (const closing of combinations([0, 1, 100], [0, 1, 2], [0, 1])) {
                const total = [0, 0, 0]
                const samples = everySecondOf(2, 1497, 5).map((second): MetricSample => {
                    const picked =
                        second === 872
                            ? inside
                            : second === 882
                              ? closing
                              : between(822, 877)(second)
                                ? [0, 0, 0]
                                : [10, 0, 0]
                    picked.forEach((count, bucket) => (total[bucket] += count))
                    const [fast, slow, past] = total
                    return {
                        ...sample(second, 0, 1),
                        role: HOGFLOW,
                        lateness: { hogflow: { '0.5': fast, '5': fast + slow, '+Inf': fast + slow + past } },
                    }
                })
                const worst = Math.max(
                    ...combinations(...closing.map(upTo))
                        .map((share) => inside.map((count, bucket) => count + share[bucket]))
                        .filter((counts) => counts.some((count) => count > 0))
                        .map(p99Bound)
                )
                const last = measure(
                    [{ name: 'pickup_p99_seconds', params: {} }],
                    evidence({ samples, drive: DRIVE, timeline: THREE_MINUTE_VALVE })
                ).find(({ key }) => key === 'hogflow_t120')!
                expect({ inside, closing, holds: last.censored === true || last.value! >= worst }).toEqual({
                    inside,
                    closing,
                    holds: true,
                })
            }
        }
    })

    it('never recovers writes in a minute that a failed probe overlaps, and keeps a probe that fails after T0 out of the baseline', () => {
        const names = ['write_latency_p99_ms', 'write_latency_recovery_seconds']
        for (const boundaryS of [700, 760, 820]) {
            for (const startOffsetMs of [-2500, -1500, -500, 500]) {
                for (const failedAfterMs of [500, 1500, 2000]) {
                    const at = atS(boundaryS) + startOffsetMs
                    const endedAt = at + failedAfterMs
                    if (endedAt < atS(700)) {
                        continue
                    }
                    const failed: WriterSample = { at, monoMs: at - FROM, ok: false, latencyMs: failedAfterMs }
                    const measured = measure(
                        names.map((name) => ({ name, params: {} })),
                        evidence({
                            writer: [...latencyWriter(() => 10), failed].sort((a, b) => a.at - b.at),
                            drive: DRIVE,
                            timeline: THREE_MINUTE_VALVE,
                        })
                    )
                    const lastOverlappedS = Math.floor((endedAt - atS(700)) / 60_000) * 60
                    const recovery = measured.find(({ name }) => name === names[1])!.value
                    expect({
                        at: new Date(at).toISOString(),
                        failedAfterMs,
                        bar: measured.find(({ key }) => key === 'bar')!.value,
                        recoveredAfterIt: recovery === null || recovery > lastOverlappedS,
                    }).toEqual({ at: new Date(at).toISOString(), failedAfterMs, bar: 20, recoveredAfterIt: true })
                }
            }
        }
    })

    const SPIKE_BEFORE_THE_ENVELOPE = (second: number): typeof QUIET =>
        second === 50 ? { due: 99, oldestDueSeconds: 99 } : QUIET

    const SHORT_BASELINE: ValveTimelineEntry[] = [{ ...VALVE, intentAt: isoAt(10) }]

    it.each<[string, string, (second: number) => Read, ValveTimelineEntry[], Omit<Measurement, 'name' | 'unit'>[]]>([
        [
            'drains once both lag series stay inside the last ten baseline minutes for a minute',
            'drain_seconds',
            (second) => (between(720, 760)(second) || second === 790 ? BACKED_UP : SPIKE_BEFORE_THE_ENVELOPE(second)),
            [VALVE],
            [{ value: 95 }],
        ],
        [
            'restarts the drained minute at a failed read',
            'drain_seconds',
            (second) => (between(720, 760)(second) ? BACKED_UP : second === 800 ? 'failed' : QUIET),
            [VALVE],
            [{ value: 105 }],
        ],
        [
            'restarts the drained minute after reads stop for longer than three samples',
            'drain_seconds',
            (second) => (between(720, 760)(second) ? BACKED_UP : between(770, 830)(second) ? 'missed' : QUIET),
            [VALVE],
            [{ value: 135 }],
        ],
        [
            'drains at once when the lag never leaves the envelope',
            'drain_seconds',
            SPIKE_BEFORE_THE_ENVELOPE,
            [VALVE],
            [{ value: 0 }],
        ],
        [
            'marks an at-once drain incomplete when reads failed for longer than three samples',
            'drain_seconds',
            (second) => (between(720, 1100)(second) ? 'failed' : QUIET),
            [VALVE],
            [{ value: 0, incomplete: true }],
        ],
        [
            'censors a drain the valve phase ends before',
            'drain_seconds',
            (second) => (between(1050, 1100)(second) ? BACKED_UP : QUIET),
            [VALVE],
            [{ value: null, censored: true }],
        ],
        [
            'measures no drain when every read in the valve phase failed',
            'drain_seconds',
            (second) => (between(700, 1099)(second) ? 'failed' : QUIET),
            [VALVE],
            [],
        ],
        [
            'measures no drain after a baseline too short to hold an envelope',
            'drain_seconds',
            (second) => (between(20, 60)(second) ? BACKED_UP : QUIET),
            SHORT_BASELINE,
            [],
        ],
        [
            'rates no new jobs over a baseline too short to measure',
            'baseline_new_jobs_per_second',
            () => QUIET,
            SHORT_BASELINE,
            [],
        ],
        [
            'drains the fail-back phase against the same envelope',
            'failback_drain_seconds',
            (second) => (between(1110, 1200)(second) ? BACKED_UP : QUIET),
            [VALVE],
            [{ value: 105 }],
        ],
        [
            'peaks the oldest due age inside the valve phase only',
            'queue_lag_peak_seconds',
            (second) =>
                between(720, 760)(second) ? BACKED_UP : second === 1200 ? { due: 1, oldestDueSeconds: 500 } : QUIET,
            [VALVE],
            [{ value: 30 }],
        ],
        [
            'marks the lag peak incomplete when reads failed for longer than three samples',
            'queue_lag_peak_seconds',
            (second) => (between(720, 1100)(second) ? 'failed' : QUIET),
            [VALVE],
            [{ value: 1, incomplete: true }],
        ],
    ])('%s', (_story, name, lag, timeline, measured) => {
        const queue = [...probedQueue(lag), { at: atS(902), error: 'Postgres at db failed: timeout' }]

        expect(measure([{ name, params: {} }], evidence({ queue, drive: DRIVE, timeline }))).toEqual(
            measured.map((value) => ({ name, unit: 's', ...value }))
        )
    })

    it('peaks the oldest due age over more reads than one call takes arguments', () => {
        const queue = probedQueue((second) => (between(720, 760)(second) ? BACKED_UP : QUIET), 0.002)

        expect(
            measure(
                [{ name: 'queue_lag_peak_seconds', params: {} }],
                evidence({ queue, drive: DRIVE, timeline: [VALVE] })
            )
        ).toEqual([{ name: 'queue_lag_peak_seconds', unit: 's', value: 30 }])
    })

    const errors = (
        atSecond: number,
        startedAtS: number,
        pgClientErrors: number,
        consumerLoopErrors: number,
        replica = 0
    ): MetricSample => ({ ...sample(atSecond, startedAtS, 1, 100, replica), pgClientErrors, consumerLoopErrors })

    it.each<[string, MetricSample[], MissedScrape[], Pick<Measurement, 'value' | 'incomplete'>[]]>([
        [
            'counts errors from the scrape before the valve to the scrape after it, summed over replicas, and flags a restart as incomplete',
            [
                errors(650, -60, 5, 1),
                errors(750, -60, 8, 1),
                errors(800, 760, 2, 3),
                errors(1050, 760, 4, 3),
                errors(1150, 760, 10, 9),
                errors(650, -60, 0, 0, 1),
                errors(1050, -60, 1, 2, 1),
                errors(1150, -60, 1, 2, 1),
            ],
            [],
            [
                { value: 14, incomplete: true },
                { value: 11, incomplete: true },
            ],
        ],
        [
            'counts the errors of a valve phase that falls between two scrapes',
            [errors(695, -60, 0, 0), errors(1105, -60, 7, 4)],
            [],
            [{ value: 7 }, { value: 4 }],
        ],
        [
            'flags errors as incomplete when a scrape inside the valve phase was missed',
            [errors(650, -60, 0, 0), errors(1150, -60, 3, 1)],
            [missedAt(900)],
            [
                { value: 3, incomplete: true },
                { value: 1, incomplete: true },
            ],
        ],
    ])('%s', (_story, samples, missed, [pgClientErrors, consumerLoopErrors]) => {
        expect(
            measure(
                [
                    { name: 'pg_client_errors', params: {} },
                    { name: 'consumer_loop_errors', params: {} },
                ],
                evidence({ samples, missed, drive: DRIVE, timeline: [VALVE] })
            )
        ).toEqual([
            { name: 'pg_client_errors', unit: 'errors', ...pgClientErrors },
            { name: 'consumer_loop_errors', unit: 'errors', ...consumerLoopErrors },
        ])
    })

    const janitor = (atS: number, startedAtS: number, janitorStalled: number, replica = 0): MetricSample => ({
        ...sample(atS, startedAtS, 1, 100, replica),
        role: 'cdp-cyclotron-v2-janitor',
        janitorStalled,
    })

    it.each<[string, MetricSample[], number]>([
        [
            'sums the jobs each janitor replica reset across a restart, and ignores other roles',
            [
                janitor(0, -60, 4),
                janitor(5, -60, 6),
                janitor(10, 7, 1),
                janitor(15, 7, 3),
                janitor(0, -60, 0, 1),
                janitor(15, -60, 2, 1),
                { ...sample(15, -60, 1), janitorStalled: 9 },
            ],
            7,
        ],
        ['counts none without a janitor sample', [sample(0, -60, 1), sample(5, -60, 1)], 0],
    ])('%s', (_story, samples, resets) => {
        expect(janitorResetsOf({ samples, sampledFrom: FROM })).toBe(resets)
    })

    it.each<[string, ValveTimelineEntry[], ReturnType<typeof phasesOf>, DriveWindow?]>([
        [
            'spans the valve phase from the earliest applied valve to the last release, whatever the timeline order',
            [
                { ...VALVE, intentAt: isoAt(900), releasedAt: isoAt(1000) },
                { ...VALVE, intentAt: isoAt(700), releasedAt: isoAt(800) },
                { ...VALVE, intentAt: undefined, releasedAt: undefined },
            ],
            {
                baseline: { from: atS(0), to: atS(700) },
                valve: { from: atS(700), to: atS(1000) },
                failback: { from: atS(1000), to: atS(1500) },
            },
        ],
        [
            'keeps the valve phase to the drive end while a valve is never released',
            [
                { ...VALVE, releasedAt: undefined },
                { ...VALVE, intentAt: isoAt(900) },
            ],
            { baseline: { from: atS(0), to: atS(700) }, valve: { from: atS(700), to: atS(1500) } },
        ],
        [
            'starts the fail-back phase at the release intent, not when the fail-back was observed',
            [{ ...FAILOVER, releaseIntentAt: isoAt(1000), releasedAt: isoAt(1040) }],
            {
                baseline: { from: atS(0), to: atS(700) },
                valve: { from: atS(700), to: atS(1000) },
                failback: { from: atS(1000), to: atS(1500) },
            },
        ],
        [
            'reads the whole drive as baseline when no valve applied',
            [{ ...VALVE, intentAt: undefined }],
            { baseline: { from: atS(0), to: atS(1500) } },
        ],
        [
            'reads the whole drive as baseline when a valve applied only after the drive ended',
            [{ ...VALVE, intentAt: isoAt(1600), releasedAt: isoAt(1700) }],
            { baseline: { from: atS(0), to: atS(1500) } },
        ],
        [
            'starts the baseline once the drive has warmed up, and ends it at the valve intent',
            [VALVE],
            {
                baseline: { from: atS(160), to: atS(700) },
                valve: { from: atS(700), to: atS(1100) },
                failback: { from: atS(1100), to: atS(1500) },
            },
            { ...DRIVE, warmedAt: atS(160) },
        ],
        [
            'reads the drive after its warm-up as baseline when no valve applied, as in the paired control',
            [],
            { baseline: { from: atS(160), to: atS(1500) } },
            { ...DRIVE, warmedAt: atS(160) },
        ],
        [
            'reads no baseline when the drive ended before it warmed up',
            [],
            { baseline: { from: atS(1500), to: atS(1500) } },
            { ...DRIVE, warmedAt: atS(1600) },
        ],
    ])('%s', (_story, timeline, phases, drive = DRIVE) => {
        expect(phasesOf(drive, timeline)).toEqual(phases)
    })

    it('rates the baseline claims per queue, new jobs and host CPU up to the valve intent, and claims per step', () => {
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
        const recorded = evidence({
            samples,
            host,
            queue: probedQueue(() => QUIET),
            drive: DRIVE,
            steps: [
                { scale: 1, fromMs: 0, toMs: 700_000 },
                { scale: 10, fromMs: 700_000, toMs: 1_500_000 },
            ],
            timeline: [VALVE],
        })

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
                scrapedSeconds: 600,
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

    it('rates claims per step from the samples inside each step, and marks a step a replica missed, left a gap in or restarted in', () => {
        const every5s = (
            fromS: number,
            toS: number,
            replica: number,
            processed: (atS: number) => Record<string, number>
        ) =>
            Array.from({ length: (toS - fromS) / 5 + 1 }, (_, i) => fromS + i * 5).map((at) => ({
                ...sample(at, -60, 1, 100, replica),
                processed: processed(at),
            }))
        const hogflowAt = (at: number): number => Math.min(at, 60) + 10 * Math.max(at - 60, 0)
        const recorded = evidence({
            samples: [
                ...every5s(0, 115, 0, (at) => ({ hogflow: hogflowAt(at) })),
                ...every5s(0, 50, 1, (at) => ({ email: 2 * at })),
                ...every5s(0, 115, 2, () => ({ hogflow: 0 })).filter(({ at }) => at <= atS(20) || at >= atS(45)),
                ...every5s(0, 115, 3, (at) => ({ fetch: at < 90 ? at : at - 87 })).map((restarting) =>
                    restarting.at >= atS(90) ? { ...restarting, startedAt: FROM / 1000 + 87 } : restarting
                ),
                ...every5s(0, 115, 4, (at) => ({ fanout: at < 60 ? at : at - 61 }))
                    .filter(({ at }) => at !== atS(60))
                    .map((restarting) =>
                        restarting.at > atS(60) ? { ...restarting, startedAt: FROM / 1000 + 61 } : restarting
                    ),
            ],
            drive: { startedAt: atS(0), endedAt: atS(120) },
            steps: [
                { scale: 1, fromMs: 0, toMs: 60_000 },
                { scale: 10, fromMs: 60_000, toMs: 120_000 },
            ],
        })

        expect(measure([{ name: 'step_claims_per_second', params: {} }], recorded)).toEqual([
            { name: 'step_claims_per_second', key: 'hogflow_1x', unit: 'jobs/s', value: 1, incomplete: true },
            { name: 'step_claims_per_second', key: 'email_1x', unit: 'jobs/s', value: 2 },
            { name: 'step_claims_per_second', key: 'fetch_1x', unit: 'jobs/s', value: 1 },
            { name: 'step_claims_per_second', key: 'fanout_1x', unit: 'jobs/s', value: 1 },
            { name: 'step_claims_per_second', key: 'hogflow_10x', unit: 'jobs/s', value: 10 },
            { name: 'step_claims_per_second', key: 'email_10x', unit: 'jobs/s', value: 0, incomplete: true },
            { name: 'step_claims_per_second', key: 'fetch_10x', unit: 'jobs/s', value: 53 / 55, incomplete: true },
            { name: 'step_claims_per_second', key: 'fanout_10x', unit: 'jobs/s', value: 1, incomplete: true },
        ])
    })

    it('rates the baseline from the end of the warm-up, not from the scrape before it, nor across a restart there, counting each lifetime once', () => {
        const every5s = Array.from({ length: 40 }, (_, i) => i * 5)
        const sinceWarmUp = (second: number, perSecond: number): number => Math.max(0, second - 160) * perSecond
        const restartedAt = 162.5
        const recorded = evidence({
            samples: [
                ...every5s.map((second) => ({
                    ...sample(second, -60, 1),
                    processed: { email: sinceWarmUp(second, 100) },
                })),
                ...every5s
                    .map((second) => second + 2.5)
                    .map((second) =>
                        second < restartedAt
                            ? { ...sample(second, -60, 1, 100, 1), processed: { email: 500 } }
                            : {
                                  ...sample(second, restartedAt, 1, 100, 1),
                                  processed: { email: 20 + (second - restartedAt) * 100 },
                              }
                    ),
                ...every5s
                    .map((second) => second + 158)
                    .filter((second) => second < 200)
                    .map((second) => ({
                        ...sample(second, 158, 1, 100, 2),
                        processed: { email: 50 + (second - 158) * 100 },
                    })),
                ...[
                    { ...sample(156, -60, 1, 100, 3), processed: { email: 500 } },
                    { ...sample(161, 158, 1, 100, 3), processed: { email: 20 } },
                    ...every5s
                        .map((second) => second + 166)
                        .filter((second) => second < 200)
                        .map((second) => ({
                            ...sample(second, 161, 1, 100, 3),
                            processed: { email: (second - 161) * 100 },
                        })),
                ],
            ],
            host: every5s.map((second) => ({
                at: atS(second),
                busyTicks: sinceWarmUp(second, 50),
                totalTicks: second * 100,
            })),
            queue: every5s.map((second) => ({
                at: atS(second),
                ...QUIET,
                running: 1,
                inserted: sinceWarmUp(second, 10),
            })),
            drive: { startedAt: atS(0), warmedAt: atS(160), endedAt: atS(200) },
        })

        expect(baselineOf(recorded)).toEqual({
            seconds: 40,
            scrapedSeconds: 35,
            claimsPerSecond: { email: 400 },
            newJobsPerSecond: 10,
            hostBusyShare: 0.5,
        })
    })

    it('rates no claims when the role metrics stop early in the baseline', () => {
        const samples: MetricSample[] = [
            { ...sample(0, -60, 1, 100), processed: {} },
            { ...sample(10, -60, 1, 100), processed: { email: 10 } },
        ]
        const recorded = evidence({ samples, queue: probedQueue(() => QUIET), drive: DRIVE, timeline: [VALVE] })

        expect(baselineOf(recorded)).toMatchObject({ seconds: 700, scrapedSeconds: 10, claimsPerSecond: {} })
    })
})
