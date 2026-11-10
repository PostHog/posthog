import { withPostgres } from '../environment/stack'

export type Queue = 'hogflow' | 'email'

export type JobCounts = { running: number; available: number; scheduledLater: number }

export interface CyclotronProbe {
    counts(query: { teams: number[]; queues: Queue[] }): Promise<JobCounts>
}

export function createCyclotronProbe(cyclotronUrl: string): CyclotronProbe {
    return {
        counts: ({ teams, queues }) =>
            withPostgres(async (client) => {
                const { rows } = await client.query<{ running: string; available: string; later: string }>(
                    `SELECT count(*) FILTER (WHERE status = 'running') AS running,
                            count(*) FILTER (WHERE status = 'available' AND scheduled <= now()) AS available,
                            count(*) FILTER (WHERE status = 'available' AND scheduled > now()) AS later
                     FROM cyclotron_jobs
                     WHERE team_id = ANY($1) AND queue_name = ANY($2) AND status IN ('available', 'running')`,
                    [teams, queues]
                )
                const [{ running, available, later }] = rows
                return { running: Number(running), available: Number(available), scheduledLater: Number(later) }
            }, cyclotronUrl),
    }
}
