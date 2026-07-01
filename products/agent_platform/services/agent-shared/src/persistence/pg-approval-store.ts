/**
 * Postgres-backed ApprovalStore. UPSERT-by-hash idempotency leans on the
 * partial unique index `agent_tool_approval_request_queued_unique`
 * declared in the corresponding migration (UNIQUE on
 * (session_id, tool_name, args_hash) WHERE state='queued').
 */

import type { Pool } from 'pg'

import { AssistantMessageRecord } from '../spec/spec'
import {
    ApprovalRequest,
    ApprovalRequestState,
    ApprovalStore,
    DecideApprovalInput,
    hashCanonicalArgs,
    ListApprovalsOpts,
    UpsertApprovalRequestInput,
    UpsertApprovalRequestResult,
} from './approval-store'

const SELECT_COLS = `id, session_id, application_id, team_id, revision_id, turn,
                     tool_call_id, tool_name, proposed_args, args_hash,
                     assistant_message, approver_scope, state,
                     decision_by, decision_at, decision_reason, decided_args,
                     dispatch_outcome, created_at, expires_at`

export class PgApprovalStore implements ApprovalStore {
    constructor(private readonly pool: Pool) {}

    async upsertQueued(input: UpsertApprovalRequestInput): Promise<UpsertApprovalRequestResult> {
        const argsHash = hashCanonicalArgs(input.proposed_args)
        // ON CONFLICT against the partial unique index — only collides with
        // an existing `queued` row. After a terminal decision a fresh insert
        // succeeds for the same (session, tool, args) tuple. DO UPDATE is a
        // no-op on the row but returns it so we can detect dedup.
        const result = await this.pool.query<DbRow & { _inserted: boolean }>(
            `INSERT INTO agent_tool_approval_request
                (id, session_id, application_id, team_id, revision_id, turn,
                 tool_call_id, tool_name, proposed_args, args_hash,
                 assistant_message, approver_scope, state,
                 created_at, expires_at)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10, $11::jsonb,
                     $12::jsonb, 'queued', NOW(), $13)
             ON CONFLICT (session_id, tool_name, args_hash) WHERE state = 'queued'
                 DO UPDATE SET tool_call_id = agent_tool_approval_request.tool_call_id
             RETURNING ${SELECT_COLS}, (xmax = 0) AS _inserted`,
            [
                input.id,
                input.session_id,
                input.application_id,
                input.team_id,
                input.revision_id,
                input.turn,
                input.tool_call_id,
                input.tool_name,
                JSON.stringify(input.proposed_args),
                argsHash,
                JSON.stringify(input.assistant_message),
                JSON.stringify(input.approver_scope),
                input.expires_at,
            ]
        )
        const row = result.rows[0]
        return { request: rowToRequest(row), deduped: !row._inserted }
    }

    async get(id: string): Promise<ApprovalRequest | null> {
        const r = await this.pool.query<DbRow>(`SELECT ${SELECT_COLS} FROM agent_tool_approval_request WHERE id = $1`, [
            id,
        ])
        return r.rowCount === 0 ? null : rowToRequest(r.rows[0])
    }

    async getForApplication(id: string, applicationId: string): Promise<ApprovalRequest | null> {
        // Tenant-scoped read for request-path callers: the row must belong to
        // the application in the request URL, so a leaked approval id can't
        // resolve another tenant's request. A miss on app mismatch returns null
        // (same as not-found) so we don't leak existence across tenants.
        const r = await this.pool.query<DbRow>(
            `SELECT ${SELECT_COLS} FROM agent_tool_approval_request WHERE id = $1 AND application_id = $2`,
            [id, applicationId]
        )
        return r.rowCount === 0 ? null : rowToRequest(r.rows[0])
    }

    async findLatestByArgs(sessionId: string, toolName: string, argsHash: Buffer): Promise<ApprovalRequest | null> {
        const r = await this.pool.query<DbRow>(
            `SELECT ${SELECT_COLS}
             FROM agent_tool_approval_request
             WHERE session_id = $1 AND tool_name = $2 AND args_hash = $3
             ORDER BY created_at DESC
             LIMIT 1`,
            [sessionId, toolName, argsHash]
        )
        return r.rowCount === 0 ? null : rowToRequest(r.rows[0])
    }

    async markApproving(id: string, input: DecideApprovalInput): Promise<ApprovalRequest | null> {
        const r = await this.pool.query<DbRow>(
            `UPDATE agent_tool_approval_request
             SET state = 'approving',
                 decision_by = $2,
                 decision_at = $3,
                 decision_reason = $4,
                 decided_args = $5::jsonb
             WHERE id = $1 AND state = 'queued'
             RETURNING ${SELECT_COLS}`,
            [
                id,
                input.decided_by,
                input.decided_at,
                input.reason ?? null,
                input.decided_args ? JSON.stringify(input.decided_args) : null,
            ]
        )
        return r.rowCount === 0 ? null : rowToRequest(r.rows[0])
    }

    async markDispatched(id: string, outcome: { result?: unknown; error?: string }): Promise<ApprovalRequest | null> {
        const nextState: ApprovalRequestState = outcome.error ? 'dispatched_failed' : 'dispatched'
        const r = await this.pool.query<DbRow>(
            `UPDATE agent_tool_approval_request
             SET state = $2,
                 dispatch_outcome = $3::jsonb
             WHERE id = $1 AND state = 'approving'
             RETURNING ${SELECT_COLS}`,
            [id, nextState, JSON.stringify(outcome)]
        )
        return r.rowCount === 0 ? null : rowToRequest(r.rows[0])
    }

    async markRejected(id: string, input: DecideApprovalInput): Promise<ApprovalRequest | null> {
        const r = await this.pool.query<DbRow>(
            `UPDATE agent_tool_approval_request
             SET state = 'rejected',
                 decision_by = $2,
                 decision_at = $3,
                 decision_reason = $4
             WHERE id = $1 AND state = 'queued'
             RETURNING ${SELECT_COLS}`,
            [id, input.decided_by, input.decided_at, input.reason ?? null]
        )
        return r.rowCount === 0 ? null : rowToRequest(r.rows[0])
    }

    async expireQueued(now: string): Promise<ApprovalRequest[]> {
        const r = await this.pool.query<DbRow>(
            `UPDATE agent_tool_approval_request
             SET state = 'expired'
             WHERE state = 'queued' AND expires_at <= $1
             RETURNING ${SELECT_COLS}`,
            [now]
        )
        return r.rows.map(rowToRequest)
    }

    async listByTeam(teamId: number, opts: ListApprovalsOpts = {}): Promise<ApprovalRequest[]> {
        return this.runList('team_id = $1', [teamId], opts)
    }

    async listByApplication(applicationId: string, opts: ListApprovalsOpts = {}): Promise<ApprovalRequest[]> {
        return this.runList('application_id = $1', [applicationId], opts)
    }

    async listBySession(sessionId: string, opts: ListApprovalsOpts = {}): Promise<ApprovalRequest[]> {
        return this.runList('session_id = $1', [sessionId], opts)
    }

    async countQueuedByTeam(teamId: number): Promise<number> {
        const r = await this.pool.query<{ count: string }>(
            `SELECT COUNT(*)::text AS count
             FROM agent_tool_approval_request
             WHERE team_id = $1 AND state = 'queued'`,
            [teamId]
        )
        return Number(r.rows[0]?.count ?? 0)
    }

    async countQueuedByApplication(applicationId: string): Promise<number> {
        const r = await this.pool.query<{ count: string }>(
            `SELECT COUNT(*)::text AS count
             FROM agent_tool_approval_request
             WHERE application_id = $1 AND state = 'queued'`,
            [applicationId]
        )
        return Number(r.rows[0]?.count ?? 0)
    }

    private async runList(
        whereSeed: string,
        seedParams: unknown[],
        opts: ListApprovalsOpts
    ): Promise<ApprovalRequest[]> {
        const where = [whereSeed]
        const params = [...seedParams]
        if (opts.state) {
            const states = Array.isArray(opts.state) ? opts.state : [opts.state]
            params.push(states)
            where.push(`state = ANY($${params.length}::text[])`)
        }
        if (opts.applicationId) {
            params.push(opts.applicationId)
            where.push(`application_id = $${params.length}`)
        }
        const limit = Math.max(1, Math.min(opts.limit ?? 100, 500))
        const offset = Math.max(0, opts.offset ?? 0)
        params.push(limit, offset)
        const r = await this.pool.query<DbRow>(
            `SELECT ${SELECT_COLS}
             FROM agent_tool_approval_request
             WHERE ${where.join(' AND ')}
             ORDER BY created_at DESC
             LIMIT $${params.length - 1} OFFSET $${params.length}`,
            params
        )
        return r.rows.map(rowToRequest)
    }
}

interface DbRow {
    id: string
    session_id: string
    application_id: string
    team_id: number
    revision_id: string
    turn: number
    tool_call_id: string
    tool_name: string
    proposed_args: unknown
    args_hash: Buffer
    assistant_message: unknown
    approver_scope: unknown
    state: string
    decision_by: string | null
    decision_at: Date | null
    decision_reason: string | null
    decided_args: unknown | null
    dispatch_outcome: unknown | null
    created_at: Date
    expires_at: Date
}

function rowToRequest(row: DbRow): ApprovalRequest {
    return {
        id: row.id,
        session_id: row.session_id,
        application_id: row.application_id,
        team_id: row.team_id,
        revision_id: row.revision_id,
        turn: row.turn,
        tool_call_id: row.tool_call_id,
        tool_name: row.tool_name,
        proposed_args: (row.proposed_args as Record<string, unknown>) ?? {},
        args_hash: Buffer.isBuffer(row.args_hash) ? row.args_hash : Buffer.from(row.args_hash),
        assistant_message: row.assistant_message as AssistantMessageRecord,
        approver_scope: row.approver_scope as ApprovalRequest['approver_scope'],
        state: row.state as ApprovalRequestState,
        decision_by: row.decision_by,
        decision_at: row.decision_at ? row.decision_at.toISOString() : null,
        decision_reason: row.decision_reason,
        decided_args: (row.decided_args as Record<string, unknown>) ?? null,
        dispatch_outcome: (row.dispatch_outcome as ApprovalRequest['dispatch_outcome']) ?? null,
        created_at: row.created_at.toISOString(),
        expires_at: row.expires_at.toISOString(),
    }
}
