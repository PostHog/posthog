import { withPostgres } from '../environment/stack'

export type Queue = 'hogflow' | 'email'

type JobQuery = { teams: number[]; queues: Queue[] }

export type QueueCounts = { due: number; running: number; oldestDueSeconds: number; inserted: number }

export type WriterBackends = { state: string; wait: string; count: number }[]

export interface CyclotronProbe {
    unfinishedJobs(query: JobQuery): Promise<number>
    runningJobs(query: JobQuery): Promise<number>
    counts(query: JobQuery): Promise<QueueCounts>
    activity(): Promise<WriterBackends>
}

export function createCyclotronProbe(
    cyclotronUrl: string,
    unconsumedIntake: () => Promise<number> = () => Promise.resolve(0),
    writerUrl?: string
): CyclotronProbe {
    const count = ({ teams, queues }: JobQuery, statuses: string[]): Promise<number> =>
        withPostgres(async (client) => {
            const { rows } = await client.query<{ jobs: string }>(
                `SELECT count(*) AS jobs
                 FROM cyclotron_jobs
                 WHERE team_id = ANY($1) AND queue_name = ANY($2) AND status::text = ANY($3)`,
                [teams, queues, statuses]
            )
            return Number(rows[0].jobs)
        }, cyclotronUrl)
    return {
        unfinishedJobs: async (query) => {
            const unconsumed = await unconsumedIntake()
            return unconsumed + (await count(query, ['available', 'running']))
        },
        runningJobs: (query) => count(query, ['running']),
        counts: ({ teams, queues }) =>
            withPostgres(async (client) => {
                const { rows } = await client.query<Record<keyof QueueCounts, string>>(
                    `SELECT
                         count(*) FILTER (WHERE status::text = 'available' AND scheduled <= now()) AS due,
                         count(*) FILTER (WHERE status::text = 'running') AS running,
                         coalesce(extract(epoch FROM now() - min(scheduled)
                             FILTER (WHERE status::text = 'available' AND scheduled <= now())), 0) AS "oldestDueSeconds",
                         (SELECT n_tup_ins FROM pg_stat_user_tables WHERE relid = 'cyclotron_jobs'::regclass) AS inserted
                     FROM cyclotron_jobs
                     WHERE team_id = ANY($1) AND queue_name = ANY($2)`,
                    [teams, queues]
                )
                const [{ due, running, oldestDueSeconds, inserted }] = rows
                return {
                    due: Number(due),
                    running: Number(running),
                    oldestDueSeconds: Number(oldestDueSeconds),
                    inserted: Number(inserted),
                }
            }, cyclotronUrl),
        activity: () =>
            writerUrl === undefined
                ? Promise.reject(new Error('no direct writer URL in a cloud run'))
                : withPostgres(async (client) => {
                      const { rows } = await client.query<{ state: string; wait: string; count: number }>(
                          `SELECT coalesce(state, 'unknown') AS state, coalesce(lower(wait_event_type), 'cpu') AS wait,
                            count(*)::int AS count
                     FROM pg_stat_activity
                     WHERE datname = current_database() AND backend_type = 'client backend' AND pid <> pg_backend_pid()
                     GROUP BY 1, 2
                     ORDER BY 1, 2`
                      )
                      return rows
                  }, writerUrl),
    }
}
