/**
 * Persistent, per-principal linked-credential store — the "stored auth" the
 * `spec.ts` SessionPrincipal comment promises ("agent_user_id → … → stored
 * auth"). One row per (agent_user, provider), encrypted at rest with the same
 * Fernet-keyed `EncryptedFields` as the session-credential broker.
 *
 * This is the SOURCE of truth (long-lived, revocable). At turn start the runner
 * resolves the current author's links from here and copies them into the
 * ephemeral per-session `CredentialBroker` that tools read — so the hot path is
 * unchanged and tokens get a tight session-scoped lifetime.
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
}

export interface IdentityCredentialStore {
    /** Upsert the linked credential for (agent_user, provider); (re)sets state active. */
    put(input: PutLinkedCredentialInput): Promise<void>
    /** Active credential for (agent_user, provider); null if absent or revoked. */
    get(agentUserId: string, provider: string): Promise<LinkedCredential | null>
    /** Mark revoked (row kept for audit). Idempotent. */
    revoke(agentUserId: string, provider: string): Promise<void>
    /** Hard-delete the link. Idempotent. */
    remove(agentUserId: string, provider: string): Promise<void>
    /** Revoke every active link for an application (archive cascade). Returns count. */
    revokeForApplication(applicationId: string): Promise<number>
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
                 encrypted_credentials, scopes, state, access_expires_at, created_at, updated_at)
             VALUES ($1, $2, $3, $4, $5, $6, $7, 'active', $8, NOW(), NOW())
             ON CONFLICT (agent_user_id, provider) DO UPDATE SET
                encrypted_credentials = EXCLUDED.encrypted_credentials,
                scopes = EXCLUDED.scopes,
                state = 'active',
                access_expires_at = EXCLUDED.access_expires_at,
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
            ]
        )
    }

    async get(agentUserId: string, provider: string): Promise<LinkedCredential | null> {
        const r = await this.pool.query<CredentialRow>(
            `SELECT encrypted_credentials, scopes, state
               FROM agent_identity_credential
              WHERE agent_user_id = $1 AND provider = $2`,
            [agentUserId, provider]
        )
        if (r.rowCount === 0 || r.rows[0].state !== 'active') {
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

    async revokeForApplication(applicationId: string): Promise<number> {
        const r = await this.pool.query(
            `UPDATE agent_identity_credential
                SET state = 'revoked', revoked_at = NOW(), updated_at = NOW()
              WHERE application_id = $1 AND state = 'active'`,
            [applicationId]
        )
        return r.rowCount ?? 0
    }
}
