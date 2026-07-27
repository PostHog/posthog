/**
 * Single-use signed-state store for an in-flight OAuth link round-trip. A
 * provider's `initiate()` writes a row binding the authorize request to
 * `(agent_user, provider)` + the PKCE verifier; the callback's `complete()`
 * atomically `consume()`s it. `consume` enforces single use (a row already
 * used, expired, or missing yields null) so a leaked/replayed callback can't
 * mint a second credential or be retargeted at another principal.
 *
 * Backed by `agent_identity_link_state` (Django-owned schema; migration 0007).
 */

import { randomUUID } from 'node:crypto'
import type { Pool } from 'pg'

export interface LinkState {
    id: string
    teamId: number
    applicationId: string
    agentUserId: string
    provider: string
    scopes: string[]
    codeVerifier: string
    redirectUri: string
}

export interface CreateLinkStateInput {
    teamId: number
    applicationId: string
    agentUserId: string
    provider: string
    scopes: string[]
    codeVerifier: string
    redirectUri: string
    /** Lifetime in ms (default 10 min). */
    ttlMs?: number
}

export interface IdentityLinkStateStore {
    /** Create a state row; returns its id (the OAuth `state` param). */
    create(input: CreateLinkStateInput): Promise<string>
    /** Read (without consuming) which app + provider a state belongs to — lets a
     *  callback rebuild the right provider before `consume`. Null if gone/used/expired. */
    peek(id: string): Promise<{ applicationId: string; provider: string } | null>
    /** Atomically consume by id: returns the row exactly once, then never again. */
    consume(id: string): Promise<LinkState | null>
    /** Janitor sweep of expired/used rows. Returns count removed. */
    sweepExpired(): Promise<number>
}

const DEFAULT_LINK_STATE_TTL_MS = 10 * 60 * 1000

// The `id` column is uuid — a malformed `state` from a tampered/garbage callback
// would otherwise make Postgres throw on the cast. Treat non-uuid as "no row".
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

interface StateRow {
    id: string
    team_id: string | number
    application_id: string
    agent_user_id: string
    provider: string
    scopes: string[] | null
    code_verifier: string
    redirect_uri: string
}

export class PgIdentityLinkStateStore implements IdentityLinkStateStore {
    constructor(private readonly pool: Pool) {}

    async create(input: CreateLinkStateInput): Promise<string> {
        const id = randomUUID()
        const expiresAt = new Date(Date.now() + (input.ttlMs ?? DEFAULT_LINK_STATE_TTL_MS))
        await this.pool.query(
            `INSERT INTO agent_identity_link_state
                (id, team_id, application_id, agent_user_id, provider, scopes,
                 code_verifier, redirect_uri, expires_at, created_at)
             VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())`,
            [
                id,
                input.teamId,
                input.applicationId,
                input.agentUserId,
                input.provider,
                input.scopes,
                input.codeVerifier,
                input.redirectUri,
                expiresAt,
            ]
        )
        return id
    }

    async peek(id: string): Promise<{ applicationId: string; provider: string } | null> {
        if (!UUID_RE.test(id)) {
            return null
        }
        const r = await this.pool.query<{ application_id: string; provider: string }>(
            `SELECT application_id, provider FROM agent_identity_link_state
              WHERE id = $1 AND used_at IS NULL AND expires_at > NOW()`,
            [id]
        )
        if (r.rowCount === 0) {
            return null
        }
        return { applicationId: r.rows[0].application_id, provider: r.rows[0].provider }
    }

    async consume(id: string): Promise<LinkState | null> {
        if (!UUID_RE.test(id)) {
            return null
        }
        // Single-use + unexpired in one atomic statement: the partial WHERE
        // guarantees a given row is returned by exactly one caller. A replayed
        // callback (same state id) finds used_at already set → no row.
        const r = await this.pool.query<StateRow>(
            `UPDATE agent_identity_link_state
                SET used_at = NOW()
              WHERE id = $1 AND used_at IS NULL AND expires_at > NOW()
              RETURNING id, team_id, application_id, agent_user_id, provider, scopes, code_verifier, redirect_uri`,
            [id]
        )
        if (r.rowCount === 0) {
            return null
        }
        const row = r.rows[0]
        return {
            id: row.id,
            teamId: Number(row.team_id),
            applicationId: row.application_id,
            agentUserId: row.agent_user_id,
            provider: row.provider,
            scopes: row.scopes ?? [],
            codeVerifier: row.code_verifier,
            redirectUri: row.redirect_uri,
        }
    }

    async sweepExpired(): Promise<number> {
        const r = await this.pool.query(
            `DELETE FROM agent_identity_link_state WHERE expires_at <= NOW() OR used_at IS NOT NULL`
        )
        return r.rowCount ?? 0
    }
}
