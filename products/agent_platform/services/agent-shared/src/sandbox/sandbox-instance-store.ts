/**
 * Durable lifecycle log for tool sandboxes. Backs the per-process
 * `SandboxPool` impls: every container / Modal sandbox the runner
 * provisions leaves a row in `agent_sandbox_instance`. A sibling
 * worker (or the janitor) reaps rows whose worker died mid-session — the
 * provider-side reapers (e.g. Docker labels + age) only see the local
 * host; this layer is the multi-worker view.
 *
 * Two impls:
 *   - `MemorySandboxInstanceStore` — tests / local dev.
 *   - `PgSandboxInstanceStore` — production, backed by the Django-owned `agent_sandbox_instance` table.
 *
 * Lifecycle: `provisioning → ready → terminated` (or `→ failed` on a
 * provisioning error). `touch()` refreshes `last_used_at` so the staleness
 * reaper doesn't murder an actively-used sandbox.
 */

import type { Pool } from 'pg'
import { v4 as uuidv4 } from 'uuid'

import type { SandboxKind } from './sandbox'

export type SandboxInstanceState = 'provisioning' | 'ready' | 'terminating' | 'terminated' | 'failed'

export interface SandboxInstanceRow {
    id: string
    team_id: number
    application_id: string
    revision_id: string
    session_id: string | null
    provider_kind: SandboxKind
    /** Provider-issued id — Docker container hash, Modal sandbox id, etc. */
    provider_sandbox_id: string
    state: SandboxInstanceState
    error_message: string
    created_at: string
    last_used_at: string | null
    terminated_at: string | null
}

export interface StaleSandboxRow {
    id: string
    state: SandboxInstanceState
    provider_kind: SandboxKind
    provider_sandbox_id: string
}

export interface SandboxInstanceStore {
    /**
     * Insert a `provisioning` row. Returns the id so the caller can update
     * the same row through the rest of the sandbox's life.
     */
    create(input: {
        team_id: number
        application_id: string
        revision_id: string
        session_id: string | null
        provider_kind: SandboxKind
    }): Promise<SandboxInstanceRow>
    /** provisioning → ready. Records the provider's external id. */
    markReady(id: string, providerSandboxId: string): Promise<void>
    /** Provisioning / invoke failed. Records (truncated) error, marks failed. */
    markFailed(id: string, errorMessage: string): Promise<void>
    /** Clean release. → terminated, terminated_at = NOW(). */
    markTerminated(id: string): Promise<void>
    /** Refresh `last_used_at`. Fire-and-forget on tool invocation. */
    touch(id: string): Promise<void>
    /** Lookup. Used by the janitor / debug tools. */
    get(id: string): Promise<SandboxInstanceRow | null>
    /**
     * Rows still alive whose `last_used_at` (or `created_at` if never touched)
     * is older than `maxAgeMs`. Janitor uses this to reap orphans.
     */
    findStale(maxAgeMs: number, limit?: number): Promise<StaleSandboxRow[]>
}

/* -------------------------------------------------------------------------- */
/* Postgres impl                                                              */
/* -------------------------------------------------------------------------- */

export class PgSandboxInstanceStore implements SandboxInstanceStore {
    constructor(private readonly pool: Pool) {}

    async create(input: {
        team_id: number
        application_id: string
        revision_id: string
        session_id: string | null
        provider_kind: SandboxKind
    }): Promise<SandboxInstanceRow> {
        const id = uuidv4()
        const r = await this.pool.query<DbRow>(
            `INSERT INTO agent_sandbox_instance
                (id, team_id, application_id, revision_id, session_id, provider_kind)
             VALUES ($1, $2, $3, $4, $5, $6)
             RETURNING ${SELECT_COLS}`,
            [id, input.team_id, input.application_id, input.revision_id, input.session_id, input.provider_kind]
        )
        return rowToRow(r.rows[0])
    }

    async markReady(id: string, providerSandboxId: string): Promise<void> {
        await this.pool.query(
            `UPDATE agent_sandbox_instance
             SET state='ready', provider_sandbox_id=$2, last_used_at=NOW()
             WHERE id=$1`,
            [id, providerSandboxId]
        )
    }

    async markFailed(id: string, errorMessage: string): Promise<void> {
        await this.pool.query(
            `UPDATE agent_sandbox_instance
             SET state='failed', error_message=$2, terminated_at=NOW()
             WHERE id=$1`,
            [id, errorMessage.slice(0, 4000)]
        )
    }

    async markTerminated(id: string): Promise<void> {
        await this.pool.query(
            `UPDATE agent_sandbox_instance
             SET state='terminated', terminated_at=NOW()
             WHERE id=$1`,
            [id]
        )
    }

    async touch(id: string): Promise<void> {
        await this.pool.query(`UPDATE agent_sandbox_instance SET last_used_at=NOW() WHERE id=$1`, [id])
    }

    async get(id: string): Promise<SandboxInstanceRow | null> {
        const r = await this.pool.query<DbRow>(`SELECT ${SELECT_COLS} FROM agent_sandbox_instance WHERE id=$1`, [id])
        return r.rowCount === 0 ? null : rowToRow(r.rows[0])
    }

    async findStale(maxAgeMs: number, limit = 100): Promise<StaleSandboxRow[]> {
        const r = await this.pool.query<{
            id: string
            state: SandboxInstanceState
            provider_kind: SandboxKind
            provider_sandbox_id: string
        }>(
            `SELECT id::text, state, provider_kind, provider_sandbox_id
             FROM agent_sandbox_instance
             WHERE state IN ('provisioning', 'ready', 'terminating')
               AND COALESCE(last_used_at, created_at) < NOW() - ($1 || ' milliseconds')::interval
             ORDER BY COALESCE(last_used_at, created_at) ASC
             LIMIT $2`,
            [String(maxAgeMs), limit]
        )
        return r.rows.map((row) => ({
            id: row.id,
            state: row.state,
            provider_kind: row.provider_kind,
            provider_sandbox_id: row.provider_sandbox_id,
        }))
    }
}

const SELECT_COLS = `id::text, team_id, application_id::text, revision_id::text,
                     session_id::text, provider_kind, provider_sandbox_id, state,
                     error_message, created_at, last_used_at, terminated_at`

interface DbRow {
    id: string
    team_id: number
    application_id: string
    revision_id: string
    session_id: string | null
    provider_kind: SandboxKind
    provider_sandbox_id: string
    state: SandboxInstanceState
    error_message: string
    created_at: Date
    last_used_at: Date | null
    terminated_at: Date | null
}

function rowToRow(row: DbRow): SandboxInstanceRow {
    return {
        id: row.id,
        team_id: row.team_id,
        application_id: row.application_id,
        revision_id: row.revision_id,
        session_id: row.session_id,
        provider_kind: row.provider_kind,
        provider_sandbox_id: row.provider_sandbox_id,
        state: row.state,
        error_message: row.error_message,
        created_at: row.created_at.toISOString(),
        last_used_at: row.last_used_at?.toISOString() ?? null,
        terminated_at: row.terminated_at?.toISOString() ?? null,
    }
}
