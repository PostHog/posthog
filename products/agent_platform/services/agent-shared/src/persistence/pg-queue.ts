/**
 * Postgres-backed SessionQueue. SELECT FOR UPDATE SKIP LOCKED for the claim.
 * Each row in `agent_session` IS the queue entry; state transitions drive
 * lifecycle.
 *
 * pending_inputs is a separate JSONB column from conversation so /send during
 * an in-flight turn doesn't race with the runner writing conversation back.
 * The runner drains pending_inputs into conversation at turn start atomically.
 */

import type { Pool, PoolClient } from 'pg'

import { createLogger } from '../runtime/logger'
import { parseTriggerMetadata } from '../runtime/trigger-metadata'
import {
    AgentSession,
    ConversationMessage,
    EMPTY_USAGE_TOTAL,
    PendingElevationRequest,
    SessionAclEntry,
    SessionUsageTotal,
} from '../spec/spec'
import { buildSearchText, SEARCH_TEXT_MAX } from '../spec/summarize-conversation'
import {
    AggregateStats,
    DecideElevationInput,
    DecideElevationResult,
    LIVE_SESSION_STATES,
    ListSessionsOpts,
    SessionQueue,
    SessionSummary,
} from './queue'

const SELECT_COLS = `id, application_id, revision_id, team_id, external_key,
                     idempotency_key, trigger_metadata, state,
                     conversation, pending_inputs, principal, retry_count,
                     usage_total, acl, pending_elevation_requests,
                     created_at, updated_at`

// List view: every summary column except the heavy conversation/JSONB blobs.
// `turn_count` + `search_text` stand in for the transcript so a page never
// detoasts it.
const SUMMARY_COLS = `id, application_id, revision_id, team_id, external_key,
                      idempotency_key, trigger_metadata, state, principal,
                      usage_total, retry_count, turn_count, search_text,
                      created_at, updated_at`

const log = createLogger('pg-queue')

export class PgSessionQueue implements SessionQueue {
    constructor(private readonly pool: Pool) {}

    async enqueue(session: AgentSession): Promise<void> {
        await this.pool.query(
            `INSERT INTO agent_session
                (id, application_id, revision_id, team_id, external_key,
                 idempotency_key, trigger_metadata, state,
                 conversation, pending_inputs, principal, retry_count,
                 usage_total, acl, pending_elevation_requests,
                 search_text, turn_count,
                 created_at, updated_at)
             VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8, $9::jsonb, $10::jsonb,
                     $11::jsonb, $12, $13::jsonb, $14::jsonb, $15::jsonb, $16, $17, $18, $19)
             ON CONFLICT (id) DO UPDATE SET
                state = EXCLUDED.state,
                conversation = EXCLUDED.conversation,
                pending_inputs = EXCLUDED.pending_inputs,
                usage_total = EXCLUDED.usage_total,
                acl = EXCLUDED.acl,
                pending_elevation_requests = EXCLUDED.pending_elevation_requests,
                search_text = EXCLUDED.search_text,
                turn_count = EXCLUDED.turn_count,
                updated_at = EXCLUDED.updated_at`,
            [
                session.id,
                session.application_id,
                session.revision_id,
                session.team_id,
                session.external_key,
                session.idempotency_key,
                session.trigger_metadata ? JSON.stringify(session.trigger_metadata) : null,
                session.state,
                JSON.stringify(session.conversation),
                JSON.stringify(session.pending_inputs),
                session.principal ? JSON.stringify(session.principal) : null,
                session.retry_count,
                JSON.stringify(session.usage_total ?? EMPTY_USAGE_TOTAL),
                JSON.stringify(session.acl ?? []),
                JSON.stringify(session.pending_elevation_requests ?? []),
                buildSearchText(session.conversation),
                session.conversation.length,
                session.created_at,
                session.updated_at,
            ]
        )
    }

    async claim(timeoutMs: number): Promise<AgentSession | null> {
        const start = Date.now()
        while (Date.now() - start < timeoutMs) {
            const claimed = await this.claimOnce()
            if (claimed) {
                return claimed
            }
            await new Promise((r) => setTimeout(r, 50))
        }
        return null
    }

    private async claimOnce(): Promise<AgentSession | null> {
        const client: PoolClient = await this.pool.connect()
        try {
            await client.query('BEGIN')
            const sel = await client.query<DbRow>(
                `SELECT ${SELECT_COLS}
                 FROM agent_session
                 WHERE state = 'queued'
                 ORDER BY created_at ASC
                 LIMIT 1
                 FOR UPDATE SKIP LOCKED`
            )
            if (sel.rowCount === 0) {
                await client.query('ROLLBACK')
                return null
            }
            const row = sel.rows[0]
            const now = new Date()
            await client.query(
                `UPDATE agent_session SET state = 'running', claimed_at = $2, updated_at = $2 WHERE id = $1`,
                [row.id, now]
            )
            await client.query('COMMIT')
            return rowToSession({ ...row, state: 'running', updated_at: now })
        } catch (err) {
            await client.query('ROLLBACK').catch(() => undefined)
            throw err
        } finally {
            client.release()
        }
    }

    async countByState(): Promise<Partial<Record<AgentSession['state'], number>>> {
        // Cheap GROUP BY over the queue's partial-state index. Sampled by the
        // janitor singleton once per sweep, not on any hot path.
        const res = await this.pool.query<{ state: AgentSession['state']; count: string }>(
            `SELECT state, count(*)::bigint AS count FROM agent_session GROUP BY state`
        )
        const out: Partial<Record<AgentSession['state'], number>> = {}
        for (const row of res.rows) {
            out[row.state] = Number(row.count)
        }
        return out
    }

    async update(sessionId: string, patch: Partial<AgentSession>): Promise<void> {
        const sets: string[] = ['updated_at = NOW()']
        const params: unknown[] = [sessionId]
        let i = 2
        if (patch.state !== undefined) {
            sets.push(`state = $${i++}`)
            params.push(patch.state)
        }
        if (patch.conversation !== undefined) {
            sets.push(`conversation = $${i++}::jsonb`)
            params.push(JSON.stringify(patch.conversation))
            sets.push(`search_text = $${i++}`)
            params.push(buildSearchText(patch.conversation))
            sets.push(`turn_count = $${i++}`)
            params.push(patch.conversation.length)
        }
        if (patch.pending_inputs !== undefined) {
            sets.push(`pending_inputs = $${i++}::jsonb`)
            params.push(JSON.stringify(patch.pending_inputs))
        }
        if (patch.external_key !== undefined) {
            sets.push(`external_key = $${i++}`)
            params.push(patch.external_key)
        }
        if (patch.usage_total !== undefined) {
            sets.push(`usage_total = $${i++}::jsonb`)
            params.push(JSON.stringify(patch.usage_total))
        }
        if (patch.acl !== undefined) {
            sets.push(`acl = $${i++}::jsonb`)
            params.push(JSON.stringify(patch.acl))
        }
        if (patch.pending_elevation_requests !== undefined) {
            sets.push(`pending_elevation_requests = $${i++}::jsonb`)
            params.push(JSON.stringify(patch.pending_elevation_requests))
        }
        await this.pool.query(`UPDATE agent_session SET ${sets.join(', ')} WHERE id = $1`, params)
    }

    async appendPendingInput(sessionId: string, msg: ConversationMessage): Promise<void> {
        await this.pool.query(
            `UPDATE agent_session
             SET pending_inputs = pending_inputs || $2::jsonb,
                 updated_at = NOW()
             WHERE id = $1`,
            [sessionId, JSON.stringify([msg])]
        )
    }

    async drainPendingInputs(sessionId: string): Promise<ConversationMessage[]> {
        // Lock the row, read pending_inputs, clear them, commit. Anything
        // a concurrent `/send` writes during this window will queue on the
        // row lock and land cleanly in the post-clear `[]` — never the
        // pre-clear list we're about to return.
        const client: PoolClient = await this.pool.connect()
        try {
            await client.query('BEGIN')
            const sel = await client.query<{ pending_inputs: unknown }>(
                `SELECT pending_inputs FROM agent_session WHERE id = $1 FOR UPDATE`,
                [sessionId]
            )
            if (sel.rowCount === 0) {
                await client.query('ROLLBACK')
                return []
            }
            const raw = sel.rows[0].pending_inputs
            const drained: ConversationMessage[] = Array.isArray(raw) ? (raw as ConversationMessage[]) : []
            if (drained.length === 0) {
                // Nothing to clear — skip the write so we don't bump
                // updated_at for a no-op (the janitor's reaper reads it).
                await client.query('COMMIT')
                return []
            }
            await client.query(
                `UPDATE agent_session
                 SET pending_inputs = '[]'::jsonb,
                     updated_at = NOW()
                 WHERE id = $1`,
                [sessionId]
            )
            await client.query('COMMIT')
            return drained
        } catch (err) {
            await client.query('ROLLBACK').catch(() => undefined)
            throw err
        } finally {
            client.release()
        }
    }

    async appendConversation(sessionId: string, msg: ConversationMessage): Promise<void> {
        // Keep turn_count + search_text current without re-reading the whole
        // transcript: bump the count and append this message's text (capped).
        const text = buildSearchText([msg])
        await this.pool.query(
            `UPDATE agent_session
             SET conversation = conversation || $2::jsonb,
                 turn_count = turn_count + 1,
                 search_text = LEFT(
                     CASE
                         WHEN $3 = '' THEN COALESCE(search_text, '')
                         WHEN COALESCE(search_text, '') = '' THEN $3
                         ELSE search_text || ' ' || $3
                     END, $4),
                 updated_at = NOW()
             WHERE id = $1`,
            [sessionId, JSON.stringify([msg]), text, SEARCH_TEXT_MAX]
        )
    }

    async appendPendingElevationRequest(sessionId: string, req: PendingElevationRequest): Promise<void> {
        await this.pool.query(
            `UPDATE agent_session
             SET pending_elevation_requests = pending_elevation_requests || $2::jsonb,
                 updated_at = NOW()
             WHERE id = $1`,
            [sessionId, JSON.stringify([req])]
        )
    }

    async decideElevationRequest(sessionId: string, input: DecideElevationInput): Promise<DecideElevationResult> {
        // Lock the row and re-read the request state inside the transaction so a
        // concurrent or replayed decision can't double-apply (e.g. append the
        // proposed message into pending_inputs twice). Whichever caller wins the
        // FOR UPDATE lock and finds the request still `pending` performs the
        // transition; the rest see it already decided and no-op.
        const client: PoolClient = await this.pool.connect()
        try {
            await client.query('BEGIN')
            const sel = await client.query<{ acl: unknown; pending_elevation_requests: unknown }>(
                `SELECT acl, pending_elevation_requests FROM agent_session WHERE id = $1 FOR UPDATE`,
                [sessionId]
            )
            if (sel.rowCount === 0) {
                await client.query('ROLLBACK')
                return { applied: false, reason: 'not_found', request: null }
            }
            const acl: SessionAclEntry[] = Array.isArray(sel.rows[0].acl) ? (sel.rows[0].acl as SessionAclEntry[]) : []
            const requests: PendingElevationRequest[] = Array.isArray(sel.rows[0].pending_elevation_requests)
                ? (sel.rows[0].pending_elevation_requests as PendingElevationRequest[])
                : []
            const request = requests.find((r) => r.id === input.requestId) ?? null
            if (!request) {
                await client.query('ROLLBACK')
                return { applied: false, reason: 'not_found', request: null }
            }
            if (request.state !== 'pending') {
                await client.query('ROLLBACK')
                return { applied: false, reason: 'not_pending', request }
            }

            const now = new Date().toISOString()
            const decisionState = input.decision === 'grant' ? ('granted' as const) : ('declined' as const)
            const updated: PendingElevationRequest = {
                ...request,
                state: decisionState,
                decision_at: now,
                decision_by: input.decidedBy,
            }
            const nextRequests = requests.map((r) => (r.id === input.requestId ? updated : r))

            if (input.decision === 'decline') {
                await client.query(
                    `UPDATE agent_session SET pending_elevation_requests = $2::jsonb, updated_at = NOW() WHERE id = $1`,
                    [sessionId, JSON.stringify(nextRequests)]
                )
                await client.query('COMMIT')
                return { applied: true, decision: 'decline', request: updated }
            }

            const aclEntry: SessionAclEntry = {
                principal: request.requester,
                granted_by: input.decidedBy,
                granted_at: now,
                expires_at:
                    input.expiresInMs != null && input.expiresInMs > 0
                        ? new Date(Date.now() + input.expiresInMs).toISOString()
                        : null,
                reason: input.reason ?? null,
                state: 'active',
            }
            // Single statement: land the ACL entry, mark the request granted,
            // replay the proposed message, and re-queue — all under the lock.
            await client.query(
                `UPDATE agent_session
                 SET acl = $2::jsonb,
                     pending_elevation_requests = $3::jsonb,
                     pending_inputs = pending_inputs || $4::jsonb,
                     state = 'queued',
                     updated_at = NOW()
                 WHERE id = $1`,
                [
                    sessionId,
                    JSON.stringify([...acl, aclEntry]),
                    JSON.stringify(nextRequests),
                    JSON.stringify([request.proposed_message]),
                ]
            )
            await client.query('COMMIT')
            return { applied: true, decision: 'grant', request: updated, aclEntry }
        } catch (err) {
            await client.query('ROLLBACK')
            throw err
        } finally {
            client.release()
        }
    }

    async get(sessionId: string): Promise<AgentSession | null> {
        const r = await this.pool.query<DbRow>(`SELECT ${SELECT_COLS} FROM agent_session WHERE id = $1`, [sessionId])
        if (r.rowCount === 0) {
            return null
        }
        return rowToSession(r.rows[0])
    }

    async getForApplication(sessionId: string, applicationId: string): Promise<AgentSession | null> {
        const r = await this.pool.query<DbRow>(
            `SELECT ${SELECT_COLS} FROM agent_session WHERE id = $1 AND application_id = $2`,
            [sessionId, applicationId]
        )
        if (r.rowCount === 0) {
            return null
        }
        return rowToSession(r.rows[0])
    }

    async findByIdempotencyKey(applicationId: string, idempotencyKey: string): Promise<AgentSession | null> {
        // Unique index on (application_id, idempotency_key) guarantees at most
        // one row matches — no ORDER BY / LIMIT needed for correctness, but
        // included as a no-op defensive guard against a future index drop.
        const r = await this.pool.query<DbRow>(
            `SELECT ${SELECT_COLS}
             FROM agent_session
             WHERE application_id = $1 AND idempotency_key = $2
             LIMIT 1`,
            [applicationId, idempotencyKey]
        )
        if (r.rowCount === 0) {
            return null
        }
        return rowToSession(r.rows[0])
    }

    async clearStaleIdempotencyKeys(cutoff: Date): Promise<number> {
        // Index-friendly: the partial unique index makes the WHERE NOT NULL
        // filter cheap (it's only scanning rows that still have a key). The
        // update also frees slots in the partial index — by the time a row
        // is 30 days old, any retry that would have collided already has.
        const r = await this.pool.query(
            `UPDATE agent_session
             SET idempotency_key = NULL
             WHERE idempotency_key IS NOT NULL
               AND created_at < $1`,
            [cutoff]
        )
        return r.rowCount ?? 0
    }

    async findByExternalKey(
        applicationId: string,
        externalKey: string,
        revisionId: string
    ): Promise<AgentSession | null> {
        // The revision scope lives in SQL, not in JS post-filtering — the
        // `ORDER BY updated_at DESC LIMIT 1` would otherwise return the most
        // recent row regardless of revision, and a JS-side reject would strand
        // any older same-revision row. Filtering in the WHERE clause guarantees
        // the lookup never reaches a session on a different revision. See the
        // interface docs.
        const r = await this.pool.query<DbRow>(
            `SELECT ${SELECT_COLS}
             FROM agent_session
             WHERE application_id = $1
               AND external_key = $2
               AND revision_id = $3
             ORDER BY updated_at DESC
             LIMIT 1`,
            [applicationId, externalKey, revisionId]
        )
        if (r.rowCount === 0) {
            return null
        }
        return rowToSession(r.rows[0])
    }

    async listByApplication(applicationId: string, opts: ListSessionsOpts = {}): Promise<AgentSession[]> {
        const limit = Math.max(1, Math.min(opts.limit ?? 100, 500))
        const offset = Math.max(0, opts.offset ?? 0)
        const { where, params } = buildSessionFilter(applicationId, opts)
        params.push(limit, offset)
        const r = await this.pool.query<DbRow>(
            `SELECT ${SELECT_COLS}
             FROM agent_session
             WHERE ${where.join(' AND ')}
             ORDER BY created_at DESC
             LIMIT $${params.length - 1} OFFSET $${params.length}`,
            params
        )
        return r.rows.map(rowToSession)
    }

    async countByApplication(
        applicationId: string,
        opts: Omit<ListSessionsOpts, 'limit' | 'offset'> = {}
    ): Promise<number> {
        const { where, params } = buildSessionFilter(applicationId, opts)
        const r = await this.pool.query<{ count: string }>(
            `SELECT COUNT(*)::text AS count FROM agent_session WHERE ${where.join(' AND ')}`,
            params
        )
        return Number(r.rows[0]?.count ?? 0)
    }

    async listSummariesByApplication(applicationId: string, opts: ListSessionsOpts = {}): Promise<SessionSummary[]> {
        const limit = Math.max(1, Math.min(opts.limit ?? 100, 500))
        const offset = Math.max(0, opts.offset ?? 0)
        const { where, params } = buildSessionFilter(applicationId, opts)
        params.push(limit, offset)
        const r = await this.pool.query<SummaryDbRow>(
            `SELECT ${SUMMARY_COLS}
             FROM agent_session
             WHERE ${where.join(' AND ')}
             ORDER BY created_at DESC
             LIMIT $${params.length - 1} OFFSET $${params.length}`,
            params
        )
        return r.rows.map(rowToSummary)
    }

    async listIdleCompleted(floorMaxAgeMs: number, limit = 200): Promise<AgentSession[]> {
        const r = await this.pool.query<DbRow>(
            `SELECT ${SELECT_COLS}
             FROM agent_session
             WHERE state = 'completed'
               AND updated_at < NOW() - ($1 || ' milliseconds')::interval
             ORDER BY updated_at ASC
             LIMIT $2`,
            [String(floorMaxAgeMs), limit]
        )
        return r.rows.map(rowToSession)
    }

    async aggregateForApplication(applicationId: string, since: string): Promise<AggregateStats> {
        return await this.aggregate('application_id = $1', [applicationId], since)
    }

    async aggregateForTeam(teamId: number, since: string): Promise<AggregateStats> {
        return await this.aggregate('team_id = $1', [teamId], since)
    }

    private async aggregate(scopeWhere: string, scopeParams: unknown[], since: string): Promise<AggregateStats> {
        // Single round-trip — Postgres rolls everything up so we don't ship
        // every row back to Node just to count it. `since` is positional so
        // the same param fills `created_at >=` and the cost/failed filters.
        const params = [...scopeParams, since, LIVE_SESSION_STATES]
        const sinceIdx = scopeParams.length + 1
        const liveStatesIdx = scopeParams.length + 2
        const r = await this.pool.query<{
            live_count: string
            sessions_in_window: string
            spend_in_window: string | null
            failed_in_window: string
            last_activity: Date | null
        }>(
            `SELECT
                COUNT(*) FILTER (WHERE state = ANY($${liveStatesIdx}::text[]))::text AS live_count,
                COUNT(*) FILTER (WHERE created_at >= $${sinceIdx})::text AS sessions_in_window,
                COALESCE(SUM((usage_total->>'cost_total')::numeric)
                    FILTER (WHERE created_at >= $${sinceIdx}), 0)::text AS spend_in_window,
                COUNT(*) FILTER (WHERE created_at >= $${sinceIdx} AND state = 'failed')::text AS failed_in_window,
                MAX(updated_at) AS last_activity
             FROM agent_session
             WHERE ${scopeWhere}`,
            params
        )
        const row = r.rows[0]
        return {
            liveCount: Number(row?.live_count ?? 0),
            sessionsInWindowCount: Number(row?.sessions_in_window ?? 0),
            spendInWindowUsd: Number(row?.spend_in_window ?? 0),
            failedInWindowCount: Number(row?.failed_in_window ?? 0),
            lastActivityAt: row?.last_activity ? row.last_activity.toISOString() : null,
        }
    }

    async listLiveForTeam(teamId: number, opts: { limit?: number } = {}): Promise<AgentSession[]> {
        const limit = Math.max(1, Math.min(opts.limit ?? 100, 500))
        const r = await this.pool.query<DbRow>(
            `SELECT ${SELECT_COLS}
             FROM agent_session
             WHERE team_id = $1 AND state = ANY($2::text[])
             ORDER BY updated_at DESC
             LIMIT $3`,
            [teamId, LIVE_SESSION_STATES, limit]
        )
        return r.rows.map(rowToSession)
    }

    async reapStuckRunning(thresholdMs: number, maxRetries: number): Promise<{ requeued: number; poisoned: number }> {
        // Two-step: re-queue stuck sessions that still have retries left,
        // then poison-pill those that don't. Single transaction so a session
        // can't slip through both states in a concurrent run.
        const client: PoolClient = await this.pool.connect()
        try {
            await client.query('BEGIN')
            const requeue = await client.query(
                `UPDATE agent_session
                 SET state = 'queued',
                     retry_count = retry_count + 1,
                     updated_at = NOW()
                 WHERE state = 'running'
                   AND claimed_at IS NOT NULL
                   AND claimed_at < NOW() - ($1 || ' milliseconds')::interval
                   AND retry_count < $2`,
                [String(thresholdMs), maxRetries]
            )
            const poison = await client.query(
                `UPDATE agent_session
                 SET state = 'failed',
                     retry_count = retry_count + 1,
                     updated_at = NOW()
                 WHERE state = 'running'
                   AND claimed_at IS NOT NULL
                   AND claimed_at < NOW() - ($1 || ' milliseconds')::interval
                   AND retry_count >= $2`,
                [String(thresholdMs), maxRetries]
            )
            await client.query('COMMIT')
            return { requeued: requeue.rowCount ?? 0, poisoned: poison.rowCount ?? 0 }
        } catch (err) {
            await client.query('ROLLBACK').catch(() => undefined)
            throw err
        } finally {
            client.release()
        }
    }

    /** Test helper — list all sessions for a given application. */
    async listForApplication(applicationId: string): Promise<AgentSession[]> {
        const r = await this.pool.query<DbRow>(
            `SELECT ${SELECT_COLS}
             FROM agent_session
             WHERE application_id = $1
             ORDER BY created_at ASC`,
            [applicationId]
        )
        return r.rows.map(rowToSession)
    }
}

interface DbRow {
    id: string
    application_id: string
    revision_id: string
    team_id: number
    external_key: string | null
    idempotency_key: string | null
    trigger_metadata: unknown
    state: string
    conversation: unknown
    pending_inputs: unknown
    principal: unknown
    retry_count: number
    usage_total: unknown
    acl: unknown
    pending_elevation_requests: unknown
    created_at: Date
    updated_at: Date
}

function buildSessionFilter(
    applicationId: string,
    opts: Omit<ListSessionsOpts, 'limit' | 'offset'>
): { where: string[]; params: unknown[] } {
    const where: string[] = ['application_id = $1']
    const params: unknown[] = [applicationId]
    if (opts.states && opts.states.length > 0) {
        params.push(opts.states)
        where.push(`state = ANY($${params.length}::text[])`)
    }
    if (opts.revisionId) {
        params.push(opts.revisionId)
        where.push(`revision_id = $${params.length}`)
    }
    if (opts.agentUserId) {
        // Match the agent_user_id stamped on the principal JSON. Only slack
        // sessions carry it today; other kinds simply won't match.
        params.push(opts.agentUserId)
        where.push(`principal->>'agent_user_id' = $${params.length}`)
    }
    if (opts.createdAfter) {
        params.push(opts.createdAfter)
        where.push(`created_at >= $${params.length}`)
    }
    if (opts.createdBefore) {
        params.push(opts.createdBefore)
        where.push(`created_at <= $${params.length}`)
    }
    if (opts.search?.trim()) {
        // id + external_key + the conversation digest (search_text) — never the
        // raw conversation JSONB. LIKE wildcards escaped so the term is literal.
        const term = `%${opts.search.trim().replace(/[\\%_]/g, '\\$&')}%`
        params.push(term)
        const idx = params.length
        where.push(`(id::text ILIKE $${idx} OR external_key ILIKE $${idx} OR search_text ILIKE $${idx})`)
    }
    return { where, params }
}

function rowToSession(row: DbRow): AgentSession {
    const triggerMetadata = parseTriggerMetadata(row.trigger_metadata)
    // Surface schema drift: a non-null JSONB blob that the discriminated union
    // can't validate becomes `null` here, which silently disables every kind-
    // gated reader (slack reply relay, failure notifier, etc.). Log so an
    // operator can see drift instead of hunting it through user reports.
    if (row.trigger_metadata !== null && triggerMetadata === null) {
        log.warn(
            {
                session_id: row.id,
                raw_kind:
                    typeof row.trigger_metadata === 'object' ? (row.trigger_metadata as { kind?: unknown }).kind : null,
            },
            'trigger_metadata_parse_failed'
        )
    }
    return {
        id: row.id,
        application_id: row.application_id,
        revision_id: row.revision_id,
        team_id: row.team_id,
        principal: (row.principal as AgentSession['principal']) ?? null,
        external_key: row.external_key,
        idempotency_key: row.idempotency_key,
        trigger_metadata: triggerMetadata,
        state: row.state as AgentSession['state'],
        conversation: Array.isArray(row.conversation) ? (row.conversation as AgentSession['conversation']) : [],
        pending_inputs: Array.isArray(row.pending_inputs) ? (row.pending_inputs as AgentSession['pending_inputs']) : [],
        retry_count: row.retry_count,
        usage_total: parseUsageTotal(row.usage_total),
        acl: Array.isArray(row.acl) ? (row.acl as SessionAclEntry[]) : [],
        pending_elevation_requests: Array.isArray(row.pending_elevation_requests)
            ? (row.pending_elevation_requests as PendingElevationRequest[])
            : [],
        created_at: row.created_at.toISOString(),
        updated_at: row.updated_at.toISOString(),
    }
}

function parseUsageTotal(raw: unknown): SessionUsageTotal {
    // Rows that predate the column default (or older snapshots in tests)
    // surface as null — fall back to zeroes so the type stays exact.
    if (!raw || typeof raw !== 'object') {
        return { ...EMPTY_USAGE_TOTAL }
    }
    return { ...EMPTY_USAGE_TOTAL, ...(raw as Partial<SessionUsageTotal>) }
}

interface SummaryDbRow {
    id: string
    application_id: string
    revision_id: string
    team_id: number
    external_key: string | null
    idempotency_key: string | null
    trigger_metadata: unknown
    state: string
    principal: unknown
    usage_total: unknown
    retry_count: number
    turn_count: number | null
    search_text: string | null
    created_at: Date
    updated_at: Date
}

function rowToSummary(row: SummaryDbRow): SessionSummary {
    return {
        id: row.id,
        application_id: row.application_id,
        revision_id: row.revision_id,
        team_id: row.team_id,
        external_key: row.external_key,
        idempotency_key: row.idempotency_key,
        trigger_metadata:
            row.trigger_metadata && typeof row.trigger_metadata === 'object'
                ? (row.trigger_metadata as Record<string, unknown>)
                : null,
        state: row.state as AgentSession['state'],
        principal: (row.principal as AgentSession['principal']) ?? null,
        usage_total: parseUsageTotal(row.usage_total),
        retry_count: row.retry_count,
        turns: row.turn_count ?? 0,
        search_text: row.search_text ?? null,
        created_at: row.created_at.toISOString(),
        updated_at: row.updated_at.toISOString(),
    }
}
