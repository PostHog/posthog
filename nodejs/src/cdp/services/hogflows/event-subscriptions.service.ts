import { createHash } from 'crypto'
import { Pool } from 'pg'

export type SubscriptionType = 'wait_step' | 'conversion'

/**
 * A resolved subscription row joined with its definition. The hot path consumer
 * query returns these so it can evaluate bytecode filters without a second fetch.
 */
export type EventSubscription = {
    id: string
    jobId: string
    definitionId: string
    teamId: number
    personId: string
    eventName: string
    type: SubscriptionType
    filters: Record<string, any> | null
    bytecode: any[] | null
    expiresAt: Date
}

/**
 * Input shape for creating a subscription. Callers pass the full definition
 * each time; createMany deduplicates definitions via content hash under the hood.
 */
export type CreateSubscriptionInput = {
    jobId: string
    teamId: number
    personId: string
    hogflowId: string
    actionId: string
    eventName: string
    type: SubscriptionType
    filters: Record<string, any> | null
    bytecode: any[] | null
    expiresAt: Date
}

type DefinitionKey = {
    hogflowId: string
    actionId: string
    type: SubscriptionType
    eventName: string
    filters: Record<string, any> | null
    bytecode: any[] | null
}

/**
 * Service for managing rows in `cyclotron_event_subscriptions` and the
 * shared `cyclotron_event_subscription_definitions` table.
 *
 * Two subscription types:
 * - `wait_step`: created by the `wait_until_event` handler for step-level event matching
 * - `conversion`: created by the executor for conversion goal event matching
 *
 * Step config (filters, bytecode) is stored once per unique definition and
 * referenced by many slim subscription rows, so batch workflows over large
 * cohorts do not duplicate the same payload 100k times.
 */
export class EventSubscriptionsService {
    constructor(private pool: Pool) {}

    async createMany(subs: CreateSubscriptionInput[]): Promise<void> {
        if (subs.length === 0) {
            return
        }

        // Group subs by definition so we upsert each unique definition once.
        const definitionsByHash = new Map<string, DefinitionKey & { contentHash: string }>()
        const subDefHashes: string[] = []

        for (const sub of subs) {
            const key: DefinitionKey = {
                hogflowId: sub.hogflowId,
                actionId: sub.actionId,
                type: sub.type,
                eventName: sub.eventName,
                filters: sub.filters,
                bytecode: sub.bytecode,
            }
            const contentHash = hashDefinition(key)
            if (!definitionsByHash.has(contentHash)) {
                definitionsByHash.set(contentHash, { ...key, contentHash })
            }
            subDefHashes.push(contentHash)
        }

        const client = await this.pool.connect()
        try {
            await client.query('BEGIN')

            // Upsert all unique definitions in one round-trip and collect their ids.
            const defs = Array.from(definitionsByHash.values())
            const hogflowIds = defs.map((d) => d.hogflowId)
            const actionIds = defs.map((d) => d.actionId)
            const types = defs.map((d) => d.type)
            const eventNames = defs.map((d) => d.eventName)
            const filtersJson = defs.map((d) => (d.filters ? JSON.stringify(d.filters) : null))
            const bytecodeJson = defs.map((d) => (d.bytecode ? JSON.stringify(d.bytecode) : null))
            const contentHashes = defs.map((d) => d.contentHash)

            const upsertResult = await client.query(
                `INSERT INTO cyclotron_event_subscription_definitions
                 (hogflow_id, action_id, type, event_name, filters, bytecode, content_hash)
                 SELECT
                    unnest($1::text[]),
                    unnest($2::text[]),
                    unnest($3::text[]),
                    unnest($4::text[]),
                    unnest($5::jsonb[]),
                    unnest($6::jsonb[]),
                    unnest($7::text[])
                 ON CONFLICT (hogflow_id, action_id, content_hash) DO UPDATE
                   SET event_name = EXCLUDED.event_name
                 RETURNING id, hogflow_id, action_id, content_hash`,
                [hogflowIds, actionIds, types, eventNames, filtersJson, bytecodeJson, contentHashes]
            )

            const idByKey = new Map<string, string>()
            for (const row of upsertResult.rows as {
                id: string
                hogflow_id: string
                action_id: string
                content_hash: string
            }[]) {
                idByKey.set(`${row.hogflow_id}|${row.action_id}|${row.content_hash}`, row.id)
            }

            // Insert slim subscription rows referencing the upserted definitions.
            const subJobIds: string[] = []
            const subDefIds: string[] = []
            const subTeamIds: number[] = []
            const subPersonIds: string[] = []
            const subEventNames: string[] = []
            const subTypes: string[] = []
            const subExpiresAt: Date[] = []

            for (let i = 0; i < subs.length; i++) {
                const sub = subs[i]
                const defKey = `${sub.hogflowId}|${sub.actionId}|${subDefHashes[i]}`
                const defId = idByKey.get(defKey)
                if (!defId) {
                    throw new Error(`Definition not found for subscription ${i}: ${defKey}`)
                }
                subJobIds.push(sub.jobId)
                subDefIds.push(defId)
                subTeamIds.push(sub.teamId)
                subPersonIds.push(String(sub.personId))
                subEventNames.push(sub.eventName)
                subTypes.push(sub.type)
                subExpiresAt.push(sub.expiresAt)
            }

            await client.query(
                `INSERT INTO cyclotron_event_subscriptions
                 (job_id, definition_id, team_id, person_id, event_name, type, expires_at)
                 SELECT
                    unnest($1::uuid[]),
                    unnest($2::uuid[]),
                    unnest($3::int[]),
                    unnest($4::text[]),
                    unnest($5::text[]),
                    unnest($6::text[]),
                    unnest($7::timestamptz[])`,
                [subJobIds, subDefIds, subTeamIds, subPersonIds, subEventNames, subTypes, subExpiresAt]
            )

            await client.query('COMMIT')
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

    async getForJob(jobId: string, type?: SubscriptionType): Promise<EventSubscription[]> {
        if (type) {
            const result = await this.pool.query(
                `SELECT es.id, es.job_id, es.definition_id, es.team_id, es.person_id, es.event_name, es.type,
                        d.filters, d.bytecode, es.expires_at
                 FROM cyclotron_event_subscriptions es
                 JOIN cyclotron_event_subscription_definitions d ON d.id = es.definition_id
                 WHERE es.job_id = $1 AND es.type = $2`,
                [jobId, type]
            )
            return result.rows.map(rowToSubscription)
        }
        const result = await this.pool.query(
            `SELECT es.id, es.job_id, es.definition_id, es.team_id, es.person_id, es.event_name, es.type,
                    d.filters, d.bytecode, es.expires_at
             FROM cyclotron_event_subscriptions es
             JOIN cyclotron_event_subscription_definitions d ON d.id = es.definition_id
             WHERE es.job_id = $1`,
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
            `SELECT es.id, es.job_id, es.definition_id, es.team_id, es.person_id, es.event_name, es.type,
                    d.filters, d.bytecode, es.expires_at
             FROM cyclotron_event_subscriptions es
             JOIN cyclotron_event_subscription_definitions d ON d.id = es.definition_id
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
     * Wake the given jobs and delete subs of the matched types for woken jobs.
     * Only wakes jobs that are still `available` (never disturbs `running` jobs).
     *
     * After this call, the worker will re-run the job. The handler/executor
     * detects that the waiting path was taken by the absence of its subs.
     *
     * Returns the number of jobs actually woken.
     */
    async wakeJobs(matches: { jobId: string; type: SubscriptionType }[]): Promise<number> {
        if (matches.length === 0) {
            return 0
        }

        const jobIds = [...new Set(matches.map((m) => m.jobId))]

        const client = await this.pool.connect()
        try {
            await client.query('BEGIN')

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

            const jobIdsByType = new Map<SubscriptionType, Set<string>>()
            for (const match of matches) {
                if (!wokenIds.has(match.jobId)) {
                    continue
                }
                const set = jobIdsByType.get(match.type) ?? new Set<string>()
                set.add(match.jobId)
                jobIdsByType.set(match.type, set)
            }

            for (const [type, jobs] of jobIdsByType) {
                await client.query(
                    `DELETE FROM cyclotron_event_subscriptions
                     WHERE job_id = ANY($1::uuid[]) AND type = $2`,
                    [[...jobs], type]
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

function hashDefinition(key: DefinitionKey): string {
    // Stable JSON serialisation via sorted keys would be nicer, but the inputs
    // are produced by the same serialiser on each park so key order is stable.
    const payload = JSON.stringify({
        type: key.type,
        event_name: key.eventName,
        filters: key.filters,
        bytecode: key.bytecode,
    })
    return createHash('sha256').update(payload).digest('hex')
}

function rowToSubscription(row: any): EventSubscription {
    return {
        id: row.id,
        jobId: row.job_id,
        definitionId: row.definition_id,
        teamId: row.team_id,
        personId: row.person_id,
        eventName: row.event_name,
        type: row.type ?? 'wait_step',
        filters: row.filters,
        bytecode: row.bytecode,
        expiresAt: row.expires_at,
    }
}
