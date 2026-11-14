import { defaultConfig } from '~/common/config/config'
import { waitForExpect } from '~/tests/helpers/expectations'

import { scratchSchema, withPostgres } from '../environment/stack'
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

    it.each<[string, Job[], number]>([
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
    ])('%s', async (_story, jobs, unfinished) => {
        await insert(jobs)

        const probe = createCyclotronProbe(PROBE_URL)

        expect(await probe.unfinishedJobs({ teams: [OURS], queues: ['hogflow', 'email'] })).toBe(unfinished)
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
})
