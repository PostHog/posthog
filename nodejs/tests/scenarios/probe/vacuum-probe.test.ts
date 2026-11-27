import { defaultConfig } from '~/common/config/config'

import { scratchSchema, withPostgres } from '../environment/stack'
import { createVacuumProbe } from './vacuum-probe'

const SCHEMA = scratchSchema(defaultConfig.CYCLOTRON_NODE_DATABASE_URL!, `scenario_vacuum_${process.pid}`, [
    'cyclotron_jobs',
])
const PROBE_URL = SCHEMA.url

const run = (sql: string): Promise<unknown> =>
    withPostgres(async (client) => {
        await client.query(sql)
        await client.query('SELECT pg_stat_force_next_flush()')
    }, PROBE_URL)

const insertJobs = (count: number): Promise<unknown> =>
    run(
        `INSERT INTO cyclotron_jobs (id, team_id, queue_name, status, priority, scheduled, created, last_transition)
         SELECT gen_random_uuid(), 1, 'hogflow', 'available', 0, now(), now(), now() FROM generate_series(1, ${count})`
    )

describe('vacuum probe', () => {
    beforeAll(async () => {
        await SCHEMA.create()
        await run('ALTER TABLE cyclotron_jobs SET (autovacuum_enabled = false)')
    })

    afterAll(async () => {
        await SCHEMA.drop()
    })

    it('reads the live and dead tuples and the sizes of cyclotron_jobs and its indexes', async () => {
        await insertJobs(400)
        await run(`DELETE FROM cyclotron_jobs WHERE ctid IN (SELECT ctid FROM cyclotron_jobs LIMIT 100)`)
        const probe = createVacuumProbe(PROBE_URL)

        const sample = await probe.sample()

        expect(sample).toMatchObject({ liveTuples: 300, deadTuples: 100, autovacuums: 0, lastAutovacuumAt: null })
        expect(sample.heapBytes).toBeGreaterThan(0)
        expect(Object.keys(sample.indexBytes)).toContain('cyclotron_jobs_pkey')
        expect(Object.values(sample.indexBytes).every((bytes) => bytes > 0)).toBe(true)
        expect(sample.vacuumingSince).toBeNull()
    })

    it('counts a vacuum and reads the dead tuples it removed', async () => {
        const probe = createVacuumProbe(PROBE_URL)
        const before = await probe.sample()

        await run('VACUUM cyclotron_jobs')
        const after = await probe.sample()

        expect(after.vacuums).toBe(before.vacuums + 1)
        expect(after.deadTuples).toBe(0)
    })

    it('reads the autovacuum settings and the storage options of the table and its indexes', async () => {
        await run('ALTER INDEX cyclotron_jobs_pkey SET (fillfactor = 80)')
        const probe = createVacuumProbe(PROBE_URL)

        const { settings, storage } = await probe.settings()

        expect(settings.autovacuum).toBe('on')
        expect(settings).toHaveProperty('autovacuum_vacuum_scale_factor')
        expect(settings).toHaveProperty('vacuum_cost_limit')
        expect(storage).toMatchObject({
            cyclotron_jobs: ['autovacuum_enabled=false'],
            cyclotron_jobs_pkey: ['fillfactor=80'],
        })
    })
})
