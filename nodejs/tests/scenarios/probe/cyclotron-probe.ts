import { withPostgres } from '../environment/stack'

export type Queue = 'hogflow' | 'email'

type JobQuery = { teams: number[]; queues: Queue[] }

export interface CyclotronProbe {
    unfinishedJobs(query: JobQuery): Promise<number>
    runningJobs(query: JobQuery): Promise<number>
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
    }
}
