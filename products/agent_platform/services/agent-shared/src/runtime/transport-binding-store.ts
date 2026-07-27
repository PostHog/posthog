/**
 * Durable transport→canonical-identity bindings. A binding records "this
 * transport principal (Slack T01:U01) authenticated as this canonical identity
 * (the authoritative provider's subject)". One canonical identity can have many
 * bindings (same person via Slack + Discord); unlink = delete a binding.
 *
 * Backed by `agent_transport_binding`.
 */

import { randomUUID } from 'node:crypto'
import type { Pool } from 'pg'

export interface TransportBinding {
    id: string
    teamId: number
    applicationId: string
    /** Transport AgentUser (principal_kind=transport, principal_id=subjectId). */
    transportAgentUserId: string
    /** Canonical identity AgentUser (principal_kind=identity:<provider>, id=subject). */
    canonicalAgentUserId: string
    /** Authoritative provider that established the binding. */
    provider: string
    createdAt: string
}

export interface BindInput {
    teamId: number
    applicationId: string
    transportAgentUserId: string
    canonicalAgentUserId: string
    provider: string
}

export interface TransportBindingStore {
    /** Resolve a transport principal to its canonical identity, if bound. */
    find(applicationId: string, transportAgentUserId: string): Promise<TransportBinding | null>
    /** Create/replace the binding for a transport principal (idempotent on
     *  (application, transportAgentUserId)). */
    bind(input: BindInput): Promise<TransportBinding>
    /** Remove a transport principal's binding (unlink). */
    unbind(applicationId: string, transportAgentUserId: string): Promise<void>
    /** All bindings for a canonical identity (audit / cascade unlink). */
    listForCanonical(applicationId: string, canonicalAgentUserId: string): Promise<TransportBinding[]>
}

/** In-memory store for tests and module-level integration. */
export class MemoryTransportBindingStore implements TransportBindingStore {
    private readonly byKey = new Map<string, TransportBinding>()

    private key(applicationId: string, transportAgentUserId: string): string {
        return `${applicationId}:${transportAgentUserId}`
    }

    async find(applicationId: string, transportAgentUserId: string): Promise<TransportBinding | null> {
        return this.byKey.get(this.key(applicationId, transportAgentUserId)) ?? null
    }

    async bind(input: BindInput): Promise<TransportBinding> {
        const k = this.key(input.applicationId, input.transportAgentUserId)
        const existing = this.byKey.get(k)
        const binding: TransportBinding = {
            id: existing?.id ?? randomUUID(),
            teamId: input.teamId,
            applicationId: input.applicationId,
            transportAgentUserId: input.transportAgentUserId,
            canonicalAgentUserId: input.canonicalAgentUserId,
            provider: input.provider,
            createdAt: existing?.createdAt ?? new Date(Date.now()).toISOString(),
        }
        this.byKey.set(k, binding)
        return binding
    }

    async unbind(applicationId: string, transportAgentUserId: string): Promise<void> {
        this.byKey.delete(this.key(applicationId, transportAgentUserId))
    }

    async listForCanonical(applicationId: string, canonicalAgentUserId: string): Promise<TransportBinding[]> {
        return [...this.byKey.values()].filter(
            (b) => b.applicationId === applicationId && b.canonicalAgentUserId === canonicalAgentUserId
        )
    }
}

interface BindingRow {
    id: string
    team_id: string | number
    application_id: string
    transport_agent_user_id: string
    canonical_agent_user_id: string
    provider: string
    created_at: string | Date
}

const SELECT_COLS = `id, team_id, application_id, transport_agent_user_id, canonical_agent_user_id, provider, created_at`

const toBinding = (r: BindingRow): TransportBinding => ({
    id: r.id,
    teamId: Number(r.team_id),
    applicationId: r.application_id,
    transportAgentUserId: r.transport_agent_user_id,
    canonicalAgentUserId: r.canonical_agent_user_id,
    provider: r.provider,
    createdAt: r.created_at instanceof Date ? r.created_at.toISOString() : r.created_at,
})

export class PgTransportBindingStore implements TransportBindingStore {
    constructor(private readonly pool: Pool) {}

    async find(applicationId: string, transportAgentUserId: string): Promise<TransportBinding | null> {
        const r = await this.pool.query<BindingRow>(
            `SELECT ${SELECT_COLS} FROM agent_transport_binding
              WHERE application_id = $1 AND transport_agent_user_id = $2`,
            [applicationId, transportAgentUserId]
        )
        return r.rowCount === 0 ? null : toBinding(r.rows[0])
    }

    async bind(input: BindInput): Promise<TransportBinding> {
        // Re-auth as a different identity replaces the binding; created_at is kept.
        const r = await this.pool.query<BindingRow>(
            `INSERT INTO agent_transport_binding
                (id, team_id, application_id, transport_agent_user_id, canonical_agent_user_id, provider, created_at)
             VALUES ($1, $2, $3, $4, $5, $6, NOW())
             ON CONFLICT (application_id, transport_agent_user_id)
             DO UPDATE SET canonical_agent_user_id = EXCLUDED.canonical_agent_user_id,
                           provider = EXCLUDED.provider
             RETURNING ${SELECT_COLS}`,
            [
                randomUUID(),
                input.teamId,
                input.applicationId,
                input.transportAgentUserId,
                input.canonicalAgentUserId,
                input.provider,
            ]
        )
        return toBinding(r.rows[0])
    }

    async unbind(applicationId: string, transportAgentUserId: string): Promise<void> {
        await this.pool.query(
            `DELETE FROM agent_transport_binding WHERE application_id = $1 AND transport_agent_user_id = $2`,
            [applicationId, transportAgentUserId]
        )
    }

    async listForCanonical(applicationId: string, canonicalAgentUserId: string): Promise<TransportBinding[]> {
        const r = await this.pool.query<BindingRow>(
            `SELECT ${SELECT_COLS} FROM agent_transport_binding
              WHERE application_id = $1 AND canonical_agent_user_id = $2
              ORDER BY created_at`,
            [applicationId, canonicalAgentUserId]
        )
        return r.rows.map(toBinding)
    }
}
