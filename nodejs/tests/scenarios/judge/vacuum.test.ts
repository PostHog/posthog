import type { VacuumRead } from '../probe/vacuum-probe'
import type { CpuPoint } from './bars'
import { MeasureEvidence, Measurement, MetricSample, measure } from './measurements'

const FROM = Date.parse('2026-01-05T10:00:00.000Z')
const atS = (second: number): number => FROM + second * 1000
const DRIVE = { startedAt: atS(0), endedAt: atS(1800) }

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
    drive: DRIVE,
    steps: [],
    timeline: [],
    truthFrom: 0,
    ...partial,
})

type Table = Partial<Extract<VacuumRead, { liveTuples: number }>>

const read = (second: number, table: Table = {}): VacuumRead => ({
    at: atS(second),
    liveTuples: 1000,
    deadTuples: 0,
    autovacuums: 0,
    vacuums: 0,
    lastAutovacuumAt: null,
    vacuumingSince: null,
    heapBytes: 100_000,
    toastBytes: 10_000,
    indexBytes: { cyclotron_jobs_pkey: 20_000, idx_cyclotron_jobs_dequeue: 30_000 },
    ...table,
})

const measured = (name: string, partial: Partial<MeasureEvidence>, params = {}): Partial<Measurement>[] =>
    measure([{ name, params }], evidence(partial)).map(({ key, value, censored, unmeasured, incomplete }) => ({
        key,
        value,
        ...(censored && { censored }),
        ...(unmeasured && { unmeasured }),
        ...(incomplete && { incomplete }),
    }))

describe('soak measurements', () => {
    it('keeps the highest dead tuple share of each window and marks a window no sample reached', () => {
        const vacuum = [
            read(10, { liveTuples: 900, deadTuples: 100 }),
            read(400, { liveTuples: 600, deadTuples: 400 }),
            read(1500, { liveTuples: 950, deadTuples: 50 }),
            { at: atS(1510), error: 'Postgres at db failed: timeout' },
        ]

        expect(measured('dead_tuple_share', { vacuum })).toEqual([
            { key: 't0', value: 0.4 },
            { key: 't600', value: null, censored: true, unmeasured: 'no vacuum sample in the window' },
            { key: 't1200', value: 0.05 },
        ])
    })

    it('reads the heap bytes per live row at the end of each window of the length the card asks for', () => {
        const vacuum = [read(10), read(290, { heapBytes: 120_000 }), read(310, { heapBytes: 150_000, liveTuples: 500 })]

        expect(
            measured('heap_bytes_per_row', { vacuum, drive: { startedAt: atS(0), endedAt: atS(600) } }, { every: '5m' })
        ).toEqual([
            { key: 't0', value: 120 },
            { key: 't300', value: 300 },
        ])
    })

    it('compares the bytes per live row of the heap and of each index at the end of the drive with its start', () => {
        const vacuum = [
            read(-5, { heapBytes: 1 }),
            read(10),
            read(1790, {
                liveTuples: 500,
                heapBytes: 100_000,
                indexBytes: { cyclotron_jobs_pkey: 20_000, idx_cyclotron_jobs_dequeue: 60_000 },
            }),
        ]

        expect(measured('bloat_growth', { vacuum })).toEqual([
            { key: 'heap', value: 2 },
            { key: 'toast', value: 2 },
            { key: 'indexes', value: 3.2 },
            { key: 'index_cyclotron_jobs_pkey', value: 2 },
            { key: 'index_idx_cyclotron_jobs_dequeue', value: 4 },
        ])
        expect(measured('index_bytes_per_row', { vacuum })).toEqual([
            { key: 'start', value: 50 },
            { key: 'end', value: 160 },
        ])
    })

    it('marks a start-to-end measure unmeasured when one sample stands for both ends, and incomplete when an end has no sample near it', () => {
        expect(measured('cyclotron_jobs_tuples', { vacuum: [read(10), { at: atS(1790), error: 'timeout' }] })).toEqual([
            { value: null, censored: true, unmeasured: 'fewer than two vacuum samples in the drive' },
        ])
        expect(measured('bloat_growth', { vacuum: [read(10), read(900, { liveTuples: 500 })] })).toEqual([
            { key: 'heap', value: 2, incomplete: true },
            { key: 'toast', value: 2, incomplete: true },
            { key: 'indexes', value: 2, incomplete: true },
            { key: 'index_cyclotron_jobs_pkey', value: 2, incomplete: true },
            { key: 'index_idx_cyclotron_jobs_dequeue', value: 2, incomplete: true },
        ])
        expect(
            measured('bloat_growth', {
                vacuum: [read(10, { liveTuples: 0 }), read(900, { liveTuples: 500 }), read(1790, { liveTuples: 0 })],
            })
        ).toEqual([])
    })

    it('keeps the longest wait since the last autovacuum in each window, censored while the table had none', () => {
        const vacuum = [
            read(500),
            read(700, { lastAutovacuumAt: atS(650) }),
            read(1100, { lastAutovacuumAt: atS(650) }),
        ]

        expect(measured('seconds_since_autovacuum', { vacuum })).toEqual([
            { key: 't0', value: 500, censored: true },
            { key: 't600', value: 450 },
            { key: 't1200', value: null, censored: true, unmeasured: 'no vacuum sample in the window' },
        ])
    })

    it('reads the pickup p99 of each queue in each window from the worker lateness histograms', () => {
        const worker = (second: number, early: number, late: number): MetricSample => ({
            role: 'cdp-cyclotron-worker-hogflow',
            replica: 0,
            at: atS(second),
            startedAt: FROM / 1000 - 60,
            cpuSeconds: 1,
            rssBytes: 1,
            processed: {},
            pgClientErrors: 0,
            consumerLoopErrors: 0,
            janitorStalled: 0,
            lateness: { hogflow: { '1': early, '10': early + late, '+Inf': early + late } },
        })
        const samples = Array.from({ length: 121 }, (_, i) => worker(i * 10, i * 100, i <= 60 ? 0 : (i - 60) * 10))

        expect(
            measured('pickup_p99_window_seconds', { samples, drive: { startedAt: atS(0), endedAt: atS(1200) } })
        ).toEqual([
            { key: 'hogflow_t0', value: 1 },
            { key: 'hogflow_t600', value: 10 },
        ])
    })

    it('leaves a window unmeasured when a worker restarts in it, since pickups it never scraped are lost', () => {
        const worker = (second: number, startedAt: number, early: number): MetricSample => ({
            role: 'cdp-cyclotron-worker-hogflow',
            replica: 0,
            at: atS(second),
            startedAt,
            cpuSeconds: 1,
            rssBytes: 1,
            processed: {},
            pgClientErrors: 0,
            consumerLoopErrors: 0,
            janitorStalled: 0,
            lateness: { hogflow: { '1': early, '10': early, '+Inf': early } },
        })
        const restartedAt = FROM / 1000 + 900
        const samples = Array.from({ length: 121 }, (_, i) =>
            i < 90 ? worker(i * 10, FROM / 1000 - 60, i * 100) : worker(i * 10, restartedAt, (i - 90) * 100)
        )

        expect(
            measured('pickup_p99_window_seconds', { samples, drive: { startedAt: atS(0), endedAt: atS(1200) } })
        ).toEqual([
            { key: 'hogflow_t0', value: 1 },
            {
                key: 'hogflow_t600',
                value: null,
                censored: true,
                unmeasured: 'a worker restarted in the window, so the pickups it had not yet reported are lost',
            },
        ])
    })

    it('counts the scrape interval that straddles a window edge in the later window only', () => {
        const worker = (second: number, early: number, late: number): MetricSample => ({
            role: 'cdp-cyclotron-worker-hogflow',
            replica: 0,
            at: atS(second),
            startedAt: FROM / 1000 - 60,
            cpuSeconds: 1,
            rssBytes: 1,
            processed: {},
            pgClientErrors: 0,
            consumerLoopErrors: 0,
            janitorStalled: 0,
            lateness: { hogflow: { '1': early, '10': early + late, '+Inf': early + late } },
        })
        const samples = Array.from({ length: 122 }, (_, i) => worker(-5 + i * 10, i * 100, i < 61 ? 0 : 1000))

        expect(
            measured('pickup_p99_window_seconds', { samples, drive: { startedAt: atS(0), endedAt: atS(1200) } })
        ).toEqual([
            { key: 'hogflow_t0', value: 1 },
            { key: 'hogflow_t600', value: 10 },
        ])
    })

    it('keeps the writer CPU peak of each window, and says why when the target has no writer CPU', () => {
        const writerCpu: CpuPoint[] = Array.from({ length: 20 }, (_, minute) => ({
            at: atS(minute * 60),
            percent: { 1: 55, 10: 41 }[minute] ?? 30,
        }))

        expect(measured('writer_cpu_percent', { writerCpu, drive: { startedAt: atS(0), endedAt: atS(1200) } })).toEqual(
            [
                { key: 't0', value: 55 },
                { key: 't600', value: 41 },
            ]
        )
        expect(
            measured('writer_cpu_percent', {
                writerCpu: { unsourced: 'the local stack has no Aurora writer to read CPU from' },
            })
        ).toEqual([
            { value: null, censored: true, unmeasured: 'the local stack has no Aurora writer to read CPU from' },
        ])
    })

    it('counts a writer CPU minute that straddles a window edge in both windows, and marks a window missing a minute', () => {
        const writerCpu: CpuPoint[] = Array.from({ length: 20 }, (_, minute) => ({
            at: atS(minute * 60),
            percent: minute === 10 ? 90 : 30,
        })).filter(({ at }) => at !== atS(19 * 60))

        expect(
            measured('writer_cpu_percent', { writerCpu, drive: { startedAt: atS(10), endedAt: atS(1210) } })
        ).toEqual([
            { key: 't0', value: 90 },
            { key: 't600', value: 90, incomplete: true },
        ])
    })
})
