import type { VacuumRead } from '../probe/vacuum-probe'
import { MeasureEvidence, Measurement, measure } from './measurements'

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

    it('marks the tuple counts unmeasured when one sample stands for both ends, and incomplete when an end has no sample near it', () => {
        expect(measured('cyclotron_jobs_tuples', { vacuum: [read(10), { at: atS(1790), error: 'timeout' }] })).toEqual([
            { value: null, censored: true, unmeasured: 'fewer than two vacuum samples in the drive' },
        ])
        expect(
            measured('cyclotron_jobs_tuples', { vacuum: [read(10), read(900, { liveTuples: 500, deadTuples: 40 })] })
        ).toEqual([
            { key: 'live_start', value: 1000, incomplete: true },
            { key: 'live_end', value: 500, incomplete: true },
            { key: 'dead_start', value: 0, incomplete: true },
            { key: 'dead_end', value: 40, incomplete: true },
            { key: 'dead_max', value: 40, incomplete: true },
        ])
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
})
