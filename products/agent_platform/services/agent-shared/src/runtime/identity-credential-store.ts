/**
 * Persistent, per-principal linked-credential store — the "stored auth" the
 * `spec.ts` SessionPrincipal comment promises ("agent_user_id → … → stored
 * auth"). One row per (agent_user, provider), encrypted at rest with the same
 * Fernet-keyed `EncryptedFields` as the session-credential broker.
 *
 * This is the SOURCE of truth (long-lived, revocable). At tool-call time the
 * runner resolves the current asker's link from here via `ctx.identity.resolve`
 * (see `createToolIdentity`); a trigger-edge bearer (e.g. PostHog Code passing a
 * posthog token) is the alternative source, held in the per-session
 * `CredentialBroker` and consulted first by the resolver. Tokens never leave
 * the runner process beyond the outbound API call.
 *
 * Backed by `agent_identity_credential` (Django-owned schema; see
 * backend/migrations/0007 + test-reset.ts SCHEMA_SQL).
 */

import { randomUUID } from 'node:crypto'
import type { Pool } from 'pg'

import { EncryptedFields } from './encryption'

/** The OAuth credential persisted per (agent_user, provider). Encrypted at rest. */
export interface StoredCredential {
    access_token: string
    refresh_token?: string
    token_type?: string
    /** Epoch ms when `access_token` expires, if the provider told us. */
    expires_at?: number
    scopes?: string[]
}

export interface LinkedCredential {
    agentUserId: string
    provider: string
    credential: StoredCredential
    scopes: string[]
}

export interface PutLinkedCredentialInput {
    teamId: number
    applicationId: string
    agentUserId: string
    provider: string
    credential: StoredCredential
    /** Granted scopes; defaults to `credential.scopes ?? []`. */
    scopes?: string[]
    /**
     * The proven external subject this link established (e.g. the PostHog user
     * uuid from /oauth/userinfo). Set only by an identity-establishing provider;
     * capability-only providers leave it undefined. Never nulled on a token
     * refresh (the put on refresh omits it → COALESCE keeps the existing value).
     */
    subject?: string
}

export interface IdentityCredentialStore {
    /** Upsert the linked credential for (agent_user, provider); (re)sets state active. */
    put(input: PutLinkedCredentialInput): Promise<void>
    /** Active credential for (agent_user, provider); null if absent or revoked. */
    get(agentUserId: string, provider: string): Promise<LinkedCredential | null>
    /**
     * AGENT BINDING SEAM — the single app-scoped credential shared by every asker
     * of a `binding: 'agent'` provider (no agent_user). Not implemented: throws
     * `agent_binding_not_implemented`. When this lands it needs an app-scoped row
     * shape (nullable `agent_user_id`) and a precedence rule: a per-user
     * (principal) link always wins over the shared credential.
     */
    getAgentScoped(applicationId: string, provider: string): Promise<LinkedCredential | null>
    /**
     * The proven external subject for an agent_user — from whichever active link
     * established identity (the one provider that stamps `subject`). Null when
     * the principal has no identity-establishing link. Used by per-asker auth to
     * resolve the PostHog identity behind a Slack principal.
     */
    getEstablishedSubject(agentUserId: string): Promise<string | null>
    /** Mark revoked (row kept for audit). Idempotent. */
    revoke(agentUserId: string, provider: string): Promise<void>
    /** Hard-delete the link. Idempotent. */
    remove(agentUserId: string, provider: string): Promise<void>
}

interface CredentialRow {
    encrypted_credentials: string
    scopes: string[] | null
    state: string
}

export class PgIdentityCredentialStore implements IdentityCredentialStore {
    private readonly fields: EncryptedFields

    constructor(
        private readonly pool: Pool,
        opts: { encryptionSaltKeys: string }
    ) {
        // Fail-closed: never write a linked credential in plaintext.
        if (!opts.encryptionSaltKeys || opts.encryptionSaltKeys.length === 0) {
            throw new Error(
                'PgIdentityCredentialStore requires ENCRYPTION_SALT_KEYS — credentials must be encrypted at rest'
            )
        }
        this.fields = new EncryptedFields(opts.encryptionSaltKeys)
    }

    async put(input: PutLinkedCredentialInput): Promise<void> {
        const ciphertext = this.fields.encrypt(JSON.stringify(input.credential))
        const scopes = input.scopes ?? input.credential.scopes ?? []
        const accessExpiresAt = input.credential.expires_at ? new Date(input.credential.expires_at) : null
        await this.pool.query(
            `INSERT INTO agent_identity_credential
                (id, team_id, application_id, agent_user_id, provider,
                 encrypted_credentials, scopes, state, access_expires_at, subject, created_at, updated_at)
             VALUES ($1, $2, $3, $4, $5, $6, $7, 'active', $8, $9, NOW(), NOW())
             ON CONFLICT (agent_user_id, provider) DO UPDATE SET
                encrypted_credentials = EXCLUDED.encrypted_credentials,
                scopes = EXCLUDED.scopes,
                state = 'active',
                access_expires_at = EXCLUDED.access_expires_at,
                -- Keep the established subject across token refreshes (which put
                -- with subject = null); only an explicit relink overwrites it.
                subject = COALESCE(EXCLUDED.subject, agent_identity_credential.subject),
                revoked_at = NULL,
                updated_at = NOW()`,
            [
                randomUUID(),
                input.teamId,
                input.applicationId,
                input.agentUserId,
                input.provider,
                ciphertext,
                scopes,
                accessExpiresAt,
                input.subject ?? null,
            ]
        )
    }

    // AGENT BINDING SEAM — see interface. App-scoped shared credentials aren't
    // stored yet (the table is keyed by agent_user_id NOT NULL); throw loudly so
    // a `binding: 'agent'` provider can never silently resolve to nothing.
    async getAgentScoped(_applicationId: string, _provider: string): Promise<LinkedCredential | null> {
        throw new Error('agent_binding_not_implemented')
    }

    async getEstablishedSubject(agentUserId: string): Promise<string | null> {
        const r = await this.pool.query<{ subject: string }>(
            // Today only `posthog` stamps a subject and (agent_user, provider) is
            // unique, so there's effectively one row — but ORDER BY makes the pick
            // deterministic (most-recently-linked) if a second identity-establishing
            // provider is ever added, rather than relying on physical row order.
            `SELECT subject FROM agent_identity_credential
              WHERE agent_user_id = $1 AND state = 'active' AND subject IS NOT NULL
              ORDER BY updated_at DESC
              LIMIT 1`,
            [agentUserId]
        )
        return r.rowCount === 0 ? null : r.rows[0].subject
    }

    async get(agentUserId: string, provider: string): Promise<LinkedCredential | null> {
        const r = await this.pool.query<CredentialRow>(
            // Filter state in SQL so a revoked row is skipped without decrypting it.
            `SELECT encrypted_credentials, scopes
               FROM agent_identity_credential
              WHERE agent_user_id = $1 AND provider = $2 AND state = 'active'`,
            [agentUserId, provider]
        )
        if (r.rowCount === 0) {
            return null
        }
        const row = r.rows[0]
        const credential = JSON.parse(this.fields.decrypt(row.encrypted_credentials)) as StoredCredential
        return { agentUserId, provider, credential, scopes: row.scopes ?? [] }
    }

    async revoke(agentUserId: string, provider: string): Promise<void> {
        await this.pool.query(
            `UPDATE agent_identity_credential
                SET state = 'revoked', revoked_at = NOW(), updated_at = NOW()
              WHERE agent_user_id = $1 AND provider = $2 AND state = 'active'`,
            [agentUserId, provider]
        )
    }

    async remove(agentUserId: string, provider: string): Promise<void> {
        await this.pool.query(`DELETE FROM agent_identity_credential WHERE agent_user_id = $1 AND provider = $2`, [
            agentUserId,
            provider,
        ])
    }
}
