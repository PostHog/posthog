import { Pool } from 'pg'

export type SubscriptionType = 'wait_step' | 'conversion'

/**
 * A single waiting subscription. One workflow invocation may have several
 * subscription rows (one per event in its `wait_until_event` config, plus
 * optional conversion goal subscriptions).
 */
export type EventSubscription = {
    id: string
    jobId: string
    teamId: number
    personId: string
    eventName: string
    type: SubscriptionType
    filters: Record<string, any> | null
    bytecode: any[] | null
    expiresAt: Date
}

export type CreateSubscriptionInput = {
    jobId: string
    teamId: number
    personId: string
    eventName: string
    type?: SubscriptionType
    filters: Record<string, any> | null
    bytecode: any[] | null
    expiresAt: Date
}

/**
 * Service for managing rows in `cyclotron_event_subscriptions`.
 *
 * Two subscription types:
 * - `wait_step`: created by the `wait_until_event` handler for step-level event matching
 * - `conversion`: created by the executor for conversion goal event matching
 *
 * The cdp-events consumer queries subscriptions when processing events and
 * wakes matched jobs by setting `cyclotron_jobs.scheduled = NOW()`.
 * Only the matched subscriptions are deleted (not all for the job), so the
 * handler/executor can distinguish which type triggered the wake.
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
        const types = subs.map((s) => s.type ?? 'wait_step')
        const filtersJson = subs.map((s) => (s.filters ? JSON.stringify(s.filters) : null))
        const bytecodeJson = subs.map((s) => (s.bytecode ? JSON.stringify(s.bytecode) : null))
        const expiresAt = subs.map((s) => s.expiresAt)

        await this.pool.query(
            `INSERT INTO cyclotron_event_subscriptions
             (job_id, team_id, person_id, event_name, type, filters, bytecode, expires_at)
             SELECT
                unnest($1::uuid[]),
                unnest($2::int[]),
                unnest($3::text[]),
                unnest($4::text[]),
                unnest($5::text[]),
                unnest($6::jsonb[]),
                unnest($7::jsonb[]),
                unnest($8::timestamptz[])`,
            [jobIds, teamIds, personIds, eventNames, types, filtersJson, bytecodeJson, expiresAt]
        )
    }

    async getForJob(jobId: string, type?: SubscriptionType): Promise<EventSubscription[]> {
        if (type) {
            const result = await this.pool.query(
                `SELECT id, job_id, team_id, person_id, event_name, type, filters, bytecode, expires_at
                 FROM cyclotron_event_subscriptions
                 WHERE job_id = $1 AND type = $2`,
                [jobId, type]
            )
            return result.rows.map(rowToSubscription)
        }
        const result = await this.pool.query(
            `SELECT id, job_id, team_id, person_id, event_name, type, filters, bytecode, expires_at
             FROM cyclotron_event_subscriptions
             WHERE job_id = $1`,
            [jobId]
        )
        return result.rows.map(rowToSubscription)
    }

    async deleteForJob(jobId: string, type?: SubscriptionType): Promise<void> {
        if (type) {
            await this.pool.query(`DELETE FROM cyclotron_event_subscriptions WHERE job_id = $1 AND type = $2`, [
                jobId,
                type,
            ])
        } else {
            await this.pool.query(`DELETE FROM cyclotron_event_subscriptions WHERE job_id = $1`, [jobId])
        }
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
            `SELECT es.id, es.job_id, es.team_id, es.person_id, es.event_name, es.type, es.filters, es.bytecode, es.expires_at
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
     * Wake the given jobs and delete only the specific matched subscriptions.
     * Only wakes jobs that are still `available` (never disturbs `running` jobs).
     * Only deletes subscriptions whose jobs were actually woken.
     * Returns the number of jobs actually woken.
     */
    async wakeJobs(jobIds: string[], subscriptionIds: string[]): Promise<number> {
        if (jobIds.length === 0) {
            return 0
        }

        // CTE ensures we only delete subscriptions for jobs that were actually
        // woken (status was 'available'). We delete only the matched subscription
        // IDs (not all for the job) so that the handler/executor can inspect
        // remaining subscriptions to distinguish wait_step vs conversion matches.
        const result = await this.pool.query(
            `WITH woken AS (
                UPDATE cyclotron_jobs
                SET scheduled = NOW()
                WHERE id = ANY($1::uuid[]) AND status = 'available'
                RETURNING id
            )
            DELETE FROM cyclotron_event_subscriptions
            WHERE id = ANY($2::uuid[]) AND job_id IN (SELECT id FROM woken)
            RETURNING job_id`,
            [jobIds, subscriptionIds]
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
        type: row.type ?? 'wait_step',
        filters: row.filters,
        bytecode: row.bytecode,
        expiresAt: row.expires_at,
    }
}
