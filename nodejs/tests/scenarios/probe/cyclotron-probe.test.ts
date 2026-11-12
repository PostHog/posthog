import { defaultConfig } from '~/common/config/config'

import { scratchSchema, withPostgres } from '../environment/stack'
import { createCyclotronProbe } from './cyclotron-probe'

const SCHEMA = scratchSchema(defaultConfig.CYCLOTRON_NODE_DATABASE_URL!, `scenario_probe_${process.pid}`, [
    'cyclotron_jobs',
])
const PROBE_URL = SCHEMA.url
const OURS = 9999101
const THEIRS = 9999102

type Job = { team: number; queue: string; status: string }

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
                     SELECT gen_random_uuid(), team, queue, status::public.cyclotronjobstatus, 0, now(), now(), now()
                     FROM unnest($1::int[], $2::text[], $3::text[]) AS job(team, queue, status)`,
                    [jobs.map((job) => job.team), jobs.map((job) => job.queue), jobs.map((job) => job.status)]
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
})
