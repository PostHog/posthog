import { defaultConfig } from '~/common/config/config'

import { scratchSchema, withPostgres } from '../environment/stack'
import { createCyclotronProbe } from './cyclotron-probe'

const SCHEMA = scratchSchema(defaultConfig.CYCLOTRON_NODE_DATABASE_URL!, `scenario_probe_${process.pid}`, [
    'cyclotron_jobs',
])
const PROBE_URL = SCHEMA.url
const OURS = 9999101
const THEIRS = 9999102

type Job = { team: number; queue: string; status: string; scheduledInS?: number; createdInS?: number }

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
                            now() + make_interval(secs => scheduled_in), now() + make_interval(secs => created_in), now()
                     FROM unnest($1::int[], $2::text[], $3::text[], $4::float8[], $5::float8[])
                         AS job(team, queue, status, scheduled_in, created_in)`,
                    [
                        jobs.map((job) => job.team),
                        jobs.map((job) => job.queue),
                        jobs.map((job) => job.status),
                        jobs.map((job) => job.scheduledInS ?? 0),
                        jobs.map((job) => job.createdInS ?? 0),
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

    it.each<[string, Job[], { due: number; running: number; oldestDueSeconds: number; created: number }]>([
        ['reads an empty queue as no lag', [], { due: 0, running: 0, oldestDueSeconds: 0, created: 0 }],
        [
            'counts due and running jobs of the teams, the oldest due age, and the jobs created since the instant given',
            [
                { team: OURS, queue: 'email', status: 'available', scheduledInS: -30, createdInS: -30 },
                { team: OURS, queue: 'hogflow', status: 'available', scheduledInS: -5, createdInS: -5 },
                { team: OURS, queue: 'hogflow', status: 'available', scheduledInS: 600, createdInS: -5 },
                { team: OURS, queue: 'email', status: 'running', scheduledInS: -400, createdInS: -400 },
                { team: OURS, queue: 'email', status: 'completed', scheduledInS: -500, createdInS: -500 },
                { team: OURS, queue: 'hog', status: 'available', scheduledInS: -900, createdInS: -5 },
                { team: THEIRS, queue: 'email', status: 'available', scheduledInS: -900, createdInS: -5 },
            ],
            { due: 2, running: 1, oldestDueSeconds: 30, created: 3 },
        ],
    ])('%s', async (_story, jobs, expected) => {
        await insert(jobs)

        const counts = await createCyclotronProbe(PROBE_URL).counts({
            teams: [OURS],
            queues: ['hogflow', 'email'],
            since: new Date(Date.now() - 60_000),
        })

        expect({ ...counts, oldestDueSeconds: Math.round(counts.oldestDueSeconds) }).toEqual(expected)
    })
})
