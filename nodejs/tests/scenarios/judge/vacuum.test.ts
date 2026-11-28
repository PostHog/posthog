import { MeasureEvidence, Measurement, measure } from './measurements'

const FROM = Date.parse('2026-01-05T10:00:00.000Z')

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
    drive: { startedAt: FROM, endedAt: FROM + 1_800_000 },
    steps: [],
    timeline: [],
    truthFrom: 0,
    ...partial,
})

const measured = (name: string, partial: Partial<MeasureEvidence>): Partial<Measurement>[] =>
    measure([{ name, params: {} }], evidence(partial)).map(({ key, value, censored, unmeasured, incomplete }) => ({
        key,
        value,
        ...(censored && { censored }),
        ...(unmeasured && { unmeasured }),
        ...(incomplete && { incomplete }),
    }))

describe('soak measurements', () => {
    it('names each autovacuum setting that differs from the profile in any spelling', () => {
        const vacuumSettings = {
            settings: {
                autovacuum: 'on',
                autovacuum_naptime: '1min',
                autovacuum_vacuum_cost_delay: '2ms',
                autovacuum_work_mem: '-1',
                autovacuum_vacuum_scale_factor: '0.2',
            },
            types: {
                autovacuum: { unit: null, vartype: 'bool' },
                autovacuum_naptime: { unit: 's', vartype: 'integer' },
                autovacuum_vacuum_cost_delay: { unit: 'ms', vartype: 'real' },
                autovacuum_work_mem: { unit: 'kB', vartype: 'integer' },
                autovacuum_vacuum_scale_factor: { unit: null, vartype: 'real' },
            },
            storage: { cyclotron_jobs: null, cyclotron_jobs_pkey: ['fillfactor=80'] },
        }
        const autovacuumProfile = {
            autovacuum: 'true',
            autovacuum_naptime: '60',
            autovacuum_vacuum_cost_delay: '2',
            autovacuum_work_mem: '-1',
            autovacuum_vacuum_scale_factor: '0.1',
        }

        expect(measured('autovacuum_settings_differ', { vacuumSettings, autovacuumProfile })).toEqual([
            { key: 'count', value: 1 },
            { key: 'autovacuum_vacuum_scale_factor', value: 1 },
        ])
        expect(
            measured('autovacuum_settings_differ', {
                vacuumSettings,
                autovacuumProfile: { autovacuum_naptime: '5s', autovacuum_nap_time: '1min' },
            })
        ).toEqual([
            { key: 'count', value: 1, incomplete: true },
            { key: 'autovacuum_naptime', value: 1 },
            {
                key: 'autovacuum_nap_time',
                value: null,
                censored: true,
                unmeasured: 'PostgreSQL has no setting autovacuum_nap_time',
            },
        ])
        expect(measured('autovacuum_settings_differ', { vacuumSettings })).toEqual([
            { value: null, censored: true, unmeasured: 'the profile names no autovacuum settings' },
        ])
    })
})
