import { Pool } from 'pg'

/**
 * A single waiting subscription. One workflow invocation may have several
 * subscription rows (one per event in its `wait_until_event` config).
 */
export type EventSubscription = {
    id: string
    jobId: string
    teamId: number
    personId: string
    eventName: string
    filters: Record<string, any> | null
    bytecode: any[] | null
    expiresAt: Date
}

export type CreateSubscriptionInput = {
    jobId: string
    teamId: number
    personId: string
    eventName: string
    filters: Record<string, any> | null
    bytecode: any[] | null
    expiresAt: Date
}

/**
 * Service for managing rows in `cyclotron_event_subscriptions`.
 *
 * - The `wait_until_event` action handler creates subscriptions when a workflow
 *   reaches the wait step, and deletes them on the timeout path.
 * - The cdp-events consumer queries subscriptions when processing events and
 *   wakes matched jobs by setting `cyclotron_jobs.scheduled = NOW()`.
 *
 * The service owns its own pg.Pool against the cyclotron-shard0 database
 * (same database as cyclotron-v2 jobs, so the FK + cascade work).
 */
export class EventSubscriptionsService {
    constructor(private pool: Pool) {}

    async createMany(subs: CreateSubscriptionInput[]): Promise<void> {
        if (subs.length === 0) {
            return
        }

        const jobIds = subs.map((s) => s.jobId)
        const teamIds = subs.map((s) => s.teamId)
        const personIds = subs.map((s) => s.personId)
        const eventNames = subs.map((s) => s.eventName)
        const filtersJson = subs.map((s) => (s.filters ? JSON.stringify(s.filters) : null))
        const bytecodeJson = subs.map((s) => (s.bytecode ? JSON.stringify(s.bytecode) : null))
        const expiresAt = subs.map((s) => s.expiresAt)

        await this.pool.query(
            `INSERT INTO cyclotron_event_subscriptions
             (job_id, team_id, person_id, event_name, filters, bytecode, expires_at)
             SELECT
                unnest($1::uuid[]),
                unnest($2::int[]),
                unnest($3::text[]),
                unnest($4::text[]),
                unnest($5::jsonb[]),
                unnest($6::jsonb[]),
                unnest($7::timestamptz[])`,
            [jobIds, teamIds, personIds, eventNames, filtersJson, bytecodeJson, expiresAt]
        )
    }

    async getForJob(jobId: string): Promise<EventSubscription[]> {
        const result = await this.pool.query(
            `SELECT id, job_id, team_id, person_id, event_name, filters, bytecode, expires_at
             FROM cyclotron_event_subscriptions
             WHERE job_id = $1`,
            [jobId]
        )
        return result.rows.map(rowToSubscription)
    }

    async deleteForJob(jobId: string): Promise<void> {
        await this.pool.query(`DELETE FROM cyclotron_event_subscriptions WHERE job_id = $1`, [jobId])
    }

    /**
     * Look up candidate subscriptions matching any of the given
     * `(team_id, event_name, person_id)` tuples in a single query.
     * Filters out expired subscriptions. The caller is expected to
     * evaluate the bytecode filters against the actual events before
     * deciding which jobs to wake.
     */
    async findMatchingForEvents(
        tuples: { teamId: number; eventName: string; personId: string }[]
    ): Promise<EventSubscription[]> {
        if (tuples.length === 0) {
            return []
        }

        const teamIds = tuples.map((t) => t.teamId)
        const eventNames = tuples.map((t) => t.eventName)
        const personIds = tuples.map((t) => t.personId)

        const result = await this.pool.query(
            `SELECT es.id, es.job_id, es.team_id, es.person_id, es.event_name, es.filters, es.bytecode, es.expires_at
             FROM cyclotron_event_subscriptions es
             INNER JOIN (
                 SELECT unnest($1::int[]) AS team_id,
                        unnest($2::text[]) AS event_name,
                        unnest($3::text[]) AS person_id
             ) AS lookups USING (team_id, event_name, person_id)
             WHERE es.expires_at > NOW()`,
            [teamIds, eventNames, personIds]
        )
        return result.rows.map(rowToSubscription)
    }

    /**
     * Wake the given jobs by setting `scheduled = NOW()` (only if still
     * `available`, never disturb a `running` job) and delete their subscriptions.
     * Returns the number of jobs actually woken.
     */
    async wakeJobs(jobIds: string[]): Promise<number> {
        if (jobIds.length === 0) {
            return 0
        }

        // Use a CTE so we only delete subscriptions for jobs that were actually
        // woken (status was 'available'). Without this, a near-simultaneous
        // timeout + event match would delete the subscriptions even though the
        // job was already 'running' from the timeout path, causing the handler
        // to incorrectly take the "matched" path.
        const result = await this.pool.query(
            `WITH woken AS (
                UPDATE cyclotron_jobs
                SET scheduled = NOW()
                WHERE id = ANY($1::uuid[]) AND status = 'available'
                RETURNING id
            )
            DELETE FROM cyclotron_event_subscriptions
            WHERE job_id IN (SELECT id FROM woken)
            RETURNING job_id`,
            [jobIds]
        )

        return result.rowCount ?? 0
    }
}

function rowToSubscription(row: any): EventSubscription {
    return {
        id: row.id,
        jobId: row.job_id,
        teamId: row.team_id,
        personId: row.person_id,
        eventName: row.event_name,
        filters: row.filters,
        bytecode: row.bytecode,
        expiresAt: row.expires_at,
    }
}
