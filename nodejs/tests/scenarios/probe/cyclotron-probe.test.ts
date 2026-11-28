import { Client } from 'pg'

import { defaultConfig } from '~/common/config/config'
import { waitForExpect } from '~/tests/helpers/expectations'

import { scratchSchema, withPostgres, writerUrlOf } from '../environment/stack'
import { Queue, QueueCounts, createCyclotronProbe } from './cyclotron-probe'

const SCHEMA = scratchSchema(defaultConfig.CYCLOTRON_NODE_DATABASE_URL!, `scenario_probe_${process.pid}`, [
    'cyclotron_jobs',
])
const PROBE_URL = SCHEMA.url
const OURS = 9999101
const THEIRS = 9999102

type Job = { team: number; queue: string; status: string; scheduledInS?: number }

describe('cyclotron probe', () => {
    beforeAll(async () => {
        await SCHEMA.create()
    })

    afterAll(async () => {
        await SCHEMA.drop()
    })

    beforeEach(async () => {
        await withPostgres((client) => client.query('DELETE FROM cyclotron_jobs'), PROBE_URL)
    })

    const insert = (jobs: Job[]): Promise<unknown> =>
        withPostgres(
            (client) =>
                client.query(
                    `INSERT INTO cyclotron_jobs (id, team_id, queue_name, status, priority, scheduled, created, last_transition)
                     SELECT gen_random_uuid(), team, queue, status::public.cyclotronjobstatus, 0,
                            now() + make_interval(secs => scheduled_in), now(), now()
                     FROM unnest($1::int[], $2::text[], $3::text[], $4::float8[])
                         AS job(team, queue, status, scheduled_in)`,
                    [
                        jobs.map((job) => job.team),
                        jobs.map((job) => job.queue),
                        jobs.map((job) => job.status),
                        jobs.map((job) => job.scheduledInS ?? 0),
                    ]
                ),
            PROBE_URL
        )

    it.each<[string, Job[], number, number?]>([
        [
            'counts available and running jobs of the teams on the hogflow and email queues',
            [
                { team: OURS, queue: 'hogflow', status: 'available' },
                { team: OURS, queue: 'hogflow', status: 'running' },
                { team: OURS, queue: 'email', status: 'available' },
                { team: OURS, queue: 'email', status: 'running' },
            ],
            4,
        ],
        [
            'skips jobs of teams outside the list',
            [
                { team: THEIRS, queue: 'hogflow', status: 'available' },
                { team: THEIRS, queue: 'email', status: 'running' },
                { team: OURS, queue: 'email', status: 'available' },
            ],
            1,
        ],
        [
            'skips jobs on other queues',
            [
                { team: OURS, queue: 'hog', status: 'available' },
                { team: OURS, queue: 'hogflow', status: 'running' },
            ],
            1,
        ],
        [
            'skips finished jobs',
            [
                { team: OURS, queue: 'hogflow', status: 'completed' },
                { team: OURS, queue: 'email', status: 'failed' },
                { team: OURS, queue: 'email', status: 'canceled' },
                { team: OURS, queue: 'hogflow', status: 'available' },
            ],
            1,
        ],
        [
            'counts the runs still on the intake topics, which no consumer has inserted yet',
            [{ team: OURS, queue: 'email', status: 'available' }],
            3,
            2,
        ],
    ])('%s', async (_story, jobs, unfinished, unconsumedIntake = 0) => {
        await insert(jobs)

        const probe = createCyclotronProbe(PROBE_URL, () => Promise.resolve(unconsumedIntake))

        expect(await probe.unfinishedJobs({ teams: [OURS], queues: ['hogflow', 'email'] })).toBe(unfinished)
    })

    it('counts a run the intake consumer inserts between reading its lag and counting the jobs', async () => {
        const probe = createCyclotronProbe(PROBE_URL, async () => {
            await insert([{ team: OURS, queue: 'email', status: 'available' }])
            return 0
        })

        expect(await probe.unfinishedJobs({ teams: [OURS], queues: ['hogflow', 'email'] })).toBe(1)
    })

    it('counts only the running jobs of the teams on the queue a valve waits for', async () => {
        await insert([
            { team: OURS, queue: 'email', status: 'running' },
            { team: OURS, queue: 'email', status: 'running' },
            { team: OURS, queue: 'email', status: 'available' },
            { team: OURS, queue: 'hogflow', status: 'running' },
            { team: THEIRS, queue: 'email', status: 'running' },
        ])

        const probe = createCyclotronProbe(PROBE_URL)

        expect(await probe.runningJobs({ teams: [OURS], queues: ['email'] })).toBe(2)
    })

    const QUEUES = { teams: [OURS], queues: ['hogflow', 'email'] as Queue[] }

    it.each<[string, Job[], Omit<QueueCounts, 'inserted'>]>([
        ['reads an empty queue as no lag', [], { due: 0, running: 0, oldestDueSeconds: 0 }],
        [
            'counts due and running jobs of the teams and the age of the oldest due one',
            [
                { team: OURS, queue: 'email', status: 'available', scheduledInS: -30 },
                { team: OURS, queue: 'hogflow', status: 'available', scheduledInS: -5 },
                { team: OURS, queue: 'hogflow', status: 'available', scheduledInS: 600 },
                { team: OURS, queue: 'email', status: 'running', scheduledInS: -400 },
                { team: OURS, queue: 'email', status: 'completed', scheduledInS: -500 },
                { team: OURS, queue: 'hog', status: 'available', scheduledInS: -900 },
                { team: THEIRS, queue: 'email', status: 'available', scheduledInS: -900 },
            ],
            { due: 2, running: 1, oldestDueSeconds: 30 },
        ],
    ])('%s', async (_story, jobs, { oldestDueSeconds, ...expected }) => {
        const insertedAt = Date.now()
        await insert(jobs)

        const { due, running, oldestDueSeconds: age } = await createCyclotronProbe(PROBE_URL).counts(QUEUES)

        expect({ due, running }).toEqual(expected)
        expect(age).toBeGreaterThanOrEqual(oldestDueSeconds)
        expect(age).toBeLessThanOrEqual(oldestDueSeconds + (Date.now() - insertedAt) / 1000)
    })

    it('counts every job inserted into the table, including the ones the janitor already deleted', async () => {
        const probe = createCyclotronProbe(PROBE_URL)
        const before = (await probe.counts(QUEUES)).inserted

        await insert([
            { team: OURS, queue: 'email', status: 'completed' },
            { team: OURS, queue: 'hogflow', status: 'completed' },
            { team: OURS, queue: 'hogflow', status: 'available' },
        ])
        await withPostgres((client) => client.query("DELETE FROM cyclotron_jobs WHERE status = 'completed'"), PROBE_URL)

        await waitForExpect(async () => expect((await probe.counts(QUEUES)).inserted - before).toBe(3))
    })

    it("refuses to read a cloud run's writer activity from the run's own or the profile's database when the host named no writer", async () => {
        const writerUrl = writerUrlOf(
            { SCENARIO_RUN_MANIFEST: '/opt/scenario/input/manifest.json', CYCLOTRON_NODE_DATABASE_URL: PROBE_URL },
            { CYCLOTRON_NODE_DATABASE_URL: PROBE_URL }
        )

        await expect(createCyclotronProbe(PROBE_URL, undefined, writerUrl).activity()).rejects.toThrow(
            'no direct writer URL in a cloud run'
        )
    })

    it("counts the other client backends of the writer's own database by state and by what an active one waits on", async () => {
        const LOCK = 9999103
        const database = `scenario_activity_${process.pid}`
        const adminUrl = defaultConfig.CYCLOTRON_NODE_DATABASE_URL!
        const isolated = new URL(adminUrl)
        isolated.pathname = `/${database}`
        await withPostgres((client) => client.query(`CREATE DATABASE ${database}`), adminUrl)
        const [holder, waiter, idle] = [0, 1, 2].map(() => new Client({ connectionString: isolated.toString() }))
        const elsewhere = new Client({ connectionString: PROBE_URL })
        const clients = [holder, waiter, idle, elsewhere]
        try {
            await Promise.all(clients.map((client) => client.connect()))
            const {
                rows: [{ pid }],
            } = await waiter.query<{ pid: number }>('SELECT pg_backend_pid() AS pid')
            await holder.query('SELECT pg_advisory_lock($1)', [LOCK])
            const waited = waiter.query('SELECT pg_advisory_lock($1)', [LOCK])
            let settled: unknown
            waited.then(
                () => {
                    settled = new Error('The waiter took the lock without waiting for it')
                },
                (error: unknown) => {
                    settled = error
                }
            )
            await Promise.all([idle.query('BEGIN'), elsewhere.query('BEGIN')])
            let blocked = false
            for (const deadline = Date.now() + 10_000; !blocked; ) {
                if (settled !== undefined) {
                    throw settled
                }
                if (Date.now() > deadline) {
                    throw new Error('Postgres never reported the waiter blocked')
                }
                const { rows } = await holder.query<{ blocked: boolean }>(
                    'SELECT cardinality(pg_blocking_pids($1)) > 0 AS blocked',
                    [pid]
                )
                blocked = rows[0].blocked
            }
            const probe = createCyclotronProbe(PROBE_URL, undefined, isolated.toString())

            expect(await probe.activity()).toEqual([
                { state: 'active', wait: 'lock', count: 1 },
                { state: 'idle', wait: 'client', count: 1 },
                { state: 'idle in transaction', wait: 'client', count: 1 },
            ])
            await holder.query('SELECT pg_advisory_unlock($1)', [LOCK])
            await waited
        } finally {
            await Promise.all(clients.map((client) => client.end().catch(() => undefined)))
            await withPostgres((client) => client.query(`DROP DATABASE IF EXISTS ${database} WITH (FORCE)`), adminUrl)
        }
    })
})
