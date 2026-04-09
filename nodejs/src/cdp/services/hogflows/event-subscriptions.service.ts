import { Pool } from 'pg'

import { logger } from '../../../utils/logger'

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
     * Look up candidate subscriptions matching `(team_id, event_name, person_id)`.
     * The caller is expected to evaluate the filters against the actual event
     * before deciding which jobs to wake.
     */
    async findMatchingForEvent(teamId: number, eventName: string, personId: string): Promise<EventSubscription[]> {
        const result = await this.pool.query(
            `SELECT id, job_id, team_id, person_id, event_name, filters, bytecode, expires_at
             FROM cyclotron_event_subscriptions
             WHERE team_id = $1 AND event_name = $2 AND person_id = $3`,
            [teamId, eventName, personId]
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

        const client = await this.pool.connect()
        try {
            await client.query('BEGIN')

            const updateResult = await client.query(
                `UPDATE cyclotron_jobs
                 SET scheduled = NOW()
                 WHERE id = ANY($1::uuid[]) AND status = 'available'`,
                [jobIds]
            )

            await client.query(`DELETE FROM cyclotron_event_subscriptions WHERE job_id = ANY($1::uuid[])`, [jobIds])

            await client.query('COMMIT')
            return updateResult.rowCount ?? 0
        } catch (err) {
            await client.query('ROLLBACK')
            logger.error('EventSubscriptionsService.wakeJobs failed', { error: String(err) })
            throw err
        } finally {
            client.release()
        }
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
