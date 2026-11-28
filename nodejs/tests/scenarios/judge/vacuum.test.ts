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
    it('marks the tuple counts unmeasured when one sample stands for both ends, and incomplete when an end has no sample within 20 seconds', () => {
        expect(measured('cyclotron_jobs_tuples', { vacuum: [read(10), { at: atS(1790), error: 'timeout' }] })).toEqual([
            { value: null, censored: true, unmeasured: 'fewer than two vacuum samples in the drive' },
        ])
        expect(
            measured('cyclotron_jobs_tuples', { vacuum: [read(20), read(1780, { liveTuples: 500, deadTuples: 40 })] })
        ).toEqual([
            { key: 'live_start', value: 1000 },
            { key: 'live_end', value: 500 },
            { key: 'dead_start', value: 0 },
            { key: 'dead_end', value: 40 },
            { key: 'dead_max', value: 40 },
        ])
        for (const vacuum of [
            [{ ...read(20), at: atS(20) + 1 }, read(1780)],
            [read(20), { ...read(1780), at: atS(1780) - 1 }],
        ]) {
            expect(measured('cyclotron_jobs_tuples', { vacuum })).toEqual(
                ['live_start', 'live_end', 'dead_start', 'dead_end', 'dead_max'].map((key) =>
                    expect.objectContaining({ key, incomplete: true })
                )
            )
        }
    })
})
