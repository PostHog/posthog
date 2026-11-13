import { withPostgres } from '../environment/stack'

export type Queue = 'hogflow' | 'email'

type JobQuery = { teams: number[]; queues: Queue[] }

export type QueueCounts = { due: number; running: number; oldestDueSeconds: number; inserted: number }

export interface CyclotronProbe {
    unfinishedJobs(query: JobQuery): Promise<number>
    runningJobs(query: JobQuery): Promise<number>
    counts(query: JobQuery): Promise<QueueCounts>
}

export function createCyclotronProbe(cyclotronUrl: string): CyclotronProbe {
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
        unfinishedJobs: (query) => count(query, ['available', 'running']),
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
    }
}
