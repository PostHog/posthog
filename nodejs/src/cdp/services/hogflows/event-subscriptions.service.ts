import { Pool } from 'pg'

export type SubscriptionType = 'wait_step' | 'conversion'

/**
 * A single waiting subscription. One workflow invocation may have several
 * subscription rows (one per event in its `wait_until_event` config, plus
 * optional conversion goal subscriptions).
 */
export type MatchedEventData = {
    event: string
    properties: Record<string, any>
    distinct_id?: string
    uuid?: string
    timestamp?: string
}

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
    matchedEvent: MatchedEventData | null
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
                `SELECT id, job_id, team_id, person_id, event_name, type, filters, bytecode, expires_at, matched_event
                 FROM cyclotron_event_subscriptions
                 WHERE job_id = $1 AND type = $2`,
                [jobId, type]
            )
            return result.rows.map(rowToSubscription)
        }
        const result = await this.pool.query(
            `SELECT id, job_id, team_id, person_id, event_name, type, filters, bytecode, expires_at, matched_event
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
            `SELECT es.id, es.job_id, es.team_id, es.person_id, es.event_name, es.type, es.filters, es.bytecode, es.expires_at, es.matched_event
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
     * Wake the given jobs and record which event matched on each subscription.
     * Only wakes jobs that are still `available` (never disturbs `running` jobs).
     *
     * Matched subscriptions are marked with `matched_event` data (not deleted)
     * so the handler can read which event fired and expose its properties as a
     * workflow variable. Unmatched subscriptions of the same type are deleted
     * (OR logic: any match means the others are no longer needed).
     *
     * The handler is responsible for cleaning up all remaining subscriptions
     * after reading the matched event data.
     *
     * Returns the number of jobs actually woken.
     */
    async wakeJobs(
        matches: { jobId: string; subscriptionId: string; type: SubscriptionType; event: MatchedEventData }[]
    ): Promise<number> {
        if (matches.length === 0) {
            return 0
        }

        const jobIds = [...new Set(matches.map((m) => m.jobId))]

        const client = await this.pool.connect()
        try {
            await client.query('BEGIN')

            // Wake the jobs
            const wokenResult = await client.query(
                `UPDATE cyclotron_jobs
                 SET scheduled = NOW()
                 WHERE id = ANY($1::uuid[]) AND status = 'available'
                 RETURNING id`,
                [jobIds]
            )
            const wokenIds = new Set((wokenResult.rows as { id: string }[]).map((r) => r.id))

            if (wokenIds.size === 0) {
                await client.query('ROLLBACK')
                return 0
            }

            // Mark matched subscriptions with event data (only for woken jobs)
            for (const match of matches) {
                if (!wokenIds.has(match.jobId)) {
                    continue
                }
                await client.query(
                    `UPDATE cyclotron_event_subscriptions
                     SET matched_event = $1
                     WHERE id = $2`,
                    [JSON.stringify(match.event), match.subscriptionId]
                )
            }

            // Delete unmatched subscriptions of the same types for woken jobs
            // (OR logic: the other events in the same group no longer need matching)
            const matchedSubIds = matches.filter((m) => wokenIds.has(m.jobId)).map((m) => m.subscriptionId)
            const matchedTypes = [...new Set(matches.map((m) => m.type))]

            if (matchedSubIds.length > 0) {
                await client.query(
                    `DELETE FROM cyclotron_event_subscriptions
                     WHERE job_id = ANY($1::uuid[])
                       AND type = ANY($2::text[])
                       AND id != ALL($3::uuid[])`,
                    [[...wokenIds], matchedTypes, matchedSubIds]
                )
            }

            await client.query('COMMIT')
            return wokenIds.size
        } catch (err) {
            try {
                await client.query('ROLLBACK')
            } catch (_) {
                // Ignore rollback errors
            }
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
        type: row.type ?? 'wait_step',
        filters: row.filters,
        bytecode: row.bytecode,
        expiresAt: row.expires_at,
        matchedEvent: row.matched_event ?? null,
    }
}
