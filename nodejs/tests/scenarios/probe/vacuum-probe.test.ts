import { randomUUID } from 'crypto'

import { defaultConfig } from '~/common/config/config'

import { withPostgres } from '../environment/stack'
import { createVacuumProbe } from './vacuum-probe'

const SERVER_URL = defaultConfig.CYCLOTRON_NODE_DATABASE_URL!
const DATABASE = `scenario_vacuum_${randomUUID().replaceAll('-', '')}`
const PROBE_URL = Object.assign(new URL(SERVER_URL), { pathname: `/${DATABASE}` }).toString()

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

const sizesOfTable = (): Promise<{ heap: number; toast: number }> =>
    withPostgres(async (client) => {
        const { rows } = await client.query<{ heap: string; toast: string }>(
            `SELECT pg_relation_size(c.oid) AS heap, pg_total_relation_size(c.reltoastrelid) AS toast
             FROM pg_class c WHERE c.oid = 'cyclotron_jobs'::regclass`
        )
        return { heap: Number(rows[0].heap), toast: Number(rows[0].toast) }
    }, PROBE_URL)

describe('vacuum probe', () => {
    beforeAll(async () => {
        await withPostgres((client) => client.query(`CREATE DATABASE ${DATABASE}`), SERVER_URL)
        await run(
            `CREATE TABLE cyclotron_jobs (
                 id uuid PRIMARY KEY, team_id int NOT NULL, queue_name text NOT NULL, status text NOT NULL,
                 priority smallint NOT NULL, scheduled timestamptz NOT NULL, created timestamptz NOT NULL,
                 last_transition timestamptz NOT NULL, state bytea
             ) WITH (autovacuum_enabled = false)`
        )
    })

    afterAll(async () => {
        await withPostgres((client) => client.query(`DROP DATABASE IF EXISTS ${DATABASE} WITH (FORCE)`), SERVER_URL)
    })

    it('reads the live and dead tuples and the sizes of cyclotron_jobs, its TOAST and its indexes', async () => {
        const probe = createVacuumProbe(PROBE_URL)
        const empty = await probe.sample()
        await insertJobs(400)
        await run(
            `UPDATE cyclotron_jobs SET state = convert_to(
                 (SELECT string_agg(md5(random()::text), '') FROM generate_series(1, 2000)), 'UTF8')
             WHERE id = (SELECT id FROM cyclotron_jobs LIMIT 1)`
        )
        await run(
            `DELETE FROM cyclotron_jobs WHERE ctid IN (SELECT ctid FROM cyclotron_jobs WHERE state IS NULL LIMIT 100)`
        )

        const sample = await probe.sample()
        const sizes = await sizesOfTable()

        expect(sample).toMatchObject({ liveTuples: 300, deadTuples: 101, autovacuums: 0, lastAutovacuumAt: null })
        expect(sample.heapBytes).toBeGreaterThan(0)
        expect(sample.toastBytes).toBeGreaterThan(empty.toastBytes)
        expect(sizes.toast).not.toEqual(sizes.heap)
        expect({ heap: sample.heapBytes, toast: sample.toastBytes }).toEqual(sizes)
        expect(Object.keys(sample.indexBytes)).toContain('cyclotron_jobs_pkey')
        expect(Object.values(sample.indexBytes).every((bytes) => bytes > 0)).toBe(true)
        expect(sample.vacuumingSince).toBeNull()
    })

    it('counts a vacuum and reads the dead tuples it removed', async () => {
        await insertJobs(50)
        await run(`DELETE FROM cyclotron_jobs WHERE ctid IN (SELECT ctid FROM cyclotron_jobs LIMIT 50)`)
        const probe = createVacuumProbe(PROBE_URL)
        const before = await probe.sample()

        await run('VACUUM cyclotron_jobs')
        const after = await probe.sample()

        expect(before.deadTuples).toBeGreaterThan(0)
        expect(after.vacuums).toBe(before.vacuums + 1)
        expect(after.deadTuples).toBe(0)
    })

    it.each([
        ['a role that reads every session', true, false],
        ['a role without pg_read_all_stats', false, true],
    ])('records whether %s sees the other sessions', async (_, readsAllStats, statsHidden) => {
        const role = `scenario_vacuum_probe_${randomUUID().replaceAll('-', '')}`
        await run(`CREATE ROLE ${role} LOGIN PASSWORD '${role}'`)
        try {
            await run(`GRANT USAGE ON SCHEMA public TO ${role}`)
            await run(`GRANT SELECT ON ALL TABLES IN SCHEMA public TO ${role}`)
            if (readsAllStats) {
                await run(`GRANT pg_read_all_stats TO ${role}`)
            }
            const url = new URL(PROBE_URL)
            url.username = role
            url.password = role

            const settings = await createVacuumProbe(url.toString()).settings()

            expect(settings.statsHidden).toBe(statsHidden)
        } finally {
            await run(`DROP OWNED BY ${role}`)
            await run(`DROP ROLE ${role}`)
        }
    })

    it('reads the autovacuum settings, and the storage options of the table and its indexes', async () => {
        await run('ALTER INDEX cyclotron_jobs_pkey SET (fillfactor = 80)')
        const server = await withPostgres(
            async (client) =>
                (await client.query<{ autovacuum: string }>(`SELECT current_setting('autovacuum') AS autovacuum`))
                    .rows[0],
            PROBE_URL
        )
        const probe = createVacuumProbe(PROBE_URL)

        const { settings, storage } = await probe.settings()

        expect(settings.autovacuum).toBe(server.autovacuum)
        expect(settings).toHaveProperty('autovacuum_vacuum_scale_factor')
        expect(settings).toHaveProperty('vacuum_cost_limit')
        expect(storage).toMatchObject({
            cyclotron_jobs: ['autovacuum_enabled=false'],
            cyclotron_jobs_pkey: ['fillfactor=80'],
        })
    })
})
