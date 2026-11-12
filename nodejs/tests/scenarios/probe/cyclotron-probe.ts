import { withPostgres } from '../environment/stack'

export type Queue = 'hogflow' | 'email'

export interface CyclotronProbe {
    unfinishedJobs(query: { teams: number[]; queues: Queue[] }): Promise<number>
}

export function createCyclotronProbe(cyclotronUrl: string): CyclotronProbe {
    return {
        unfinishedJobs: ({ teams, queues }) =>
            withPostgres(async (client) => {
                const { rows } = await client.query<{ unfinished: string }>(
                    `SELECT count(*) AS unfinished
                     FROM cyclotron_jobs
                     WHERE team_id = ANY($1) AND queue_name = ANY($2) AND status IN ('available', 'running')`,
                    [teams, queues]
                )
                return Number(rows[0].unfinished)
            }, cyclotronUrl),
    }
}
