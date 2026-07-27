/**
 * IdentityStore — stable identity for external users (Slack, IdP, etc.) that
 * interact with a deployed agent. Each (application, principal_kind, principal_id)
 * tuple resolves to a stable `AgentUser` row that persists across sessions.
 *
 * Backed by `agent_user` in Postgres. Tests use `PgIdentityStore` against the
 * test DB; there is no in-memory variant.
 */

import type { Pool } from 'pg'
import { v4 as uuidv4 } from 'uuid'

export interface AgentUser {
    id: string
    team_id: number
    application_id: string
    /** "slack" | "discord" | "external" | etc. — provider-specific identity namespace. */
    principal_kind: string
    /** Provider-issued stable id (e.g. "T01ABC:U12345" for Slack). */
    principal_id: string
    metadata?: Record<string, unknown>
    created_at: string
}

export interface IdentityStore {
    /**
     * Resolve or create the AgentUser for this (application, principal_kind,
     * principal_id) tuple. Same tuple → same row across calls.
     */
    findOrCreate(input: {
        team_id: number
        application_id: string
        principal_kind: string
        principal_id: string
        metadata?: Record<string, unknown>
    }): Promise<AgentUser>
    /** Lookup only (no create). Returns null if no row exists. */
    find(input: { application_id: string; principal_kind: string; principal_id: string }): Promise<AgentUser | null>
    /** Lookup by AgentUser uuid. Returns null when the row doesn't exist. */
    getById(agentUserId: string): Promise<AgentUser | null>
}

export class PgIdentityStore implements IdentityStore {
    constructor(private readonly pool: Pool) {}

    async findOrCreate(input: {
        team_id: number
        application_id: string
        principal_kind: string
        principal_id: string
        metadata?: Record<string, unknown>
    }): Promise<AgentUser> {
        // UPSERT on the natural key. ON CONFLICT DO NOTHING returns nothing
        // for the existing-row case; follow up with a SELECT.
        const id = uuidv4()
        await this.pool.query(
            `INSERT INTO agent_user (id, team_id, application_id, principal_kind, principal_id, metadata)
             VALUES ($1, $2, $3, $4, $5, $6::jsonb)
             ON CONFLICT (application_id, principal_kind, principal_id) DO NOTHING`,
            [
                id,
                input.team_id,
                input.application_id,
                input.principal_kind,
                input.principal_id,
                JSON.stringify(input.metadata ?? {}),
            ]
        )
        const existing = await this.find({
            application_id: input.application_id,
            principal_kind: input.principal_kind,
            principal_id: input.principal_id,
        })
        if (!existing) {
            throw new Error('agent_user upsert race — no row found after insert')
        }
        return existing
    }

    async find(input: {
        application_id: string
        principal_kind: string
        principal_id: string
    }): Promise<AgentUser | null> {
        const r = await this.pool.query<{
            id: string
            team_id: number
            application_id: string
            principal_kind: string
            principal_id: string
            metadata: unknown
            created_at: Date
        }>(
            `SELECT id, team_id, application_id, principal_kind, principal_id, metadata, created_at
             FROM agent_user
             WHERE application_id = $1 AND principal_kind = $2 AND principal_id = $3`,
            [input.application_id, input.principal_kind, input.principal_id]
        )
        if (r.rowCount === 0) {
            return null
        }
        const row = r.rows[0]
        return {
            id: row.id,
            team_id: row.team_id,
            application_id: row.application_id,
            principal_kind: row.principal_kind,
            principal_id: row.principal_id,
            metadata: (row.metadata as Record<string, unknown>) ?? undefined,
            created_at: row.created_at.toISOString(),
        }
    }

    async getById(agentUserId: string): Promise<AgentUser | null> {
        const r = await this.pool.query<{
            id: string
            team_id: number
            application_id: string
            principal_kind: string
            principal_id: string
            metadata: unknown
            created_at: Date
        }>(
            `SELECT id, team_id, application_id, principal_kind, principal_id, metadata, created_at
             FROM agent_user
             WHERE id = $1`,
            [agentUserId]
        )
        if (r.rowCount === 0) {
            return null
        }
        const row = r.rows[0]
        return {
            id: row.id,
            team_id: row.team_id,
            application_id: row.application_id,
            principal_kind: row.principal_kind,
            principal_id: row.principal_id,
            metadata: (row.metadata as Record<string, unknown>) ?? undefined,
            created_at: row.created_at.toISOString(),
        }
    }
}
