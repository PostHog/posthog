/**
 * Postgres-backed `CredentialBroker`. Storage shape matches the
 * Django-owned `agent_session_credential` table (see
 * products/agent_platform/backend/models.py + migrations/).
 *
 * **Encryption at rest.** The credentials map is encrypted with the
 * platform's `EncryptedFields` (same Fernet-keyed mechanism used for
 * `AgentApplication.encrypted_env`) before it lands in the DB. Rows on
 * disk are opaque ciphertext; only a process with the matching
 * `ENCRYPTION_SALT_KEYS` env can decrypt. Key rotation works through
 * `EncryptedFields`' multi-key try-each-in-order decrypt path — same
 * contract as the env block.
 *
 * One row per session; `write` upserts (so /send refreshing a rotated
 * OAuth token replaces cleanly); `resolve` returns null on expiry or
 * missing target; `clear` deletes the row.
 *
 * The harness and prod both use this — keeping a single backing store
 * across environments so "real e2e" tests exercise the same SQL path
 * production hits. Tests inject a deterministic key string at cluster
 * build time (see `buildCluster` in agent-tests).
 */

import type { Pool } from 'pg'

import { Credential, CredentialBroker, CredentialMap, DEFAULT_CREDENTIAL_TTL_MS } from './credential-broker'
import { EncryptedFields } from './encryption'

interface EncryptedRow {
    encrypted_credentials: string
    expires_at: Date
}

export class PgCredentialBroker implements CredentialBroker {
    private readonly fields: EncryptedFields

    constructor(
        private readonly pool: Pool,
        opts: { encryptionSaltKeys: string }
    ) {
        // Throws synchronously if no keys are supplied — fail-closed so a
        // misconfigured deploy can't quietly write plaintext tokens.
        if (!opts.encryptionSaltKeys || opts.encryptionSaltKeys.length === 0) {
            throw new Error('PgCredentialBroker requires ENCRYPTION_SALT_KEYS — credentials must be encrypted at rest')
        }
        this.fields = new EncryptedFields(opts.encryptionSaltKeys)
    }

    async write(sessionId: string, credentials: CredentialMap, opts: { ttlMs?: number } = {}): Promise<void> {
        const ttlMs = opts.ttlMs ?? DEFAULT_CREDENTIAL_TTL_MS
        const expiresAt = new Date(Date.now() + ttlMs)
        const ciphertext = this.fields.encrypt(JSON.stringify(credentials))
        await this.pool.query(
            `INSERT INTO agent_session_credential (session_id, encrypted_credentials, expires_at)
             VALUES ($1, $2, $3)
             ON CONFLICT (session_id) DO UPDATE SET
                encrypted_credentials = EXCLUDED.encrypted_credentials,
                expires_at = EXCLUDED.expires_at,
                updated_at = NOW()`,
            [sessionId, ciphertext, expiresAt]
        )
    }

    async resolve(sessionId: string, target: string): Promise<Credential | null> {
        const r = await this.pool.query<EncryptedRow>(
            `SELECT encrypted_credentials, expires_at
               FROM agent_session_credential
              WHERE session_id = $1`,
            [sessionId]
        )
        if (r.rowCount === 0) {
            return null
        }
        const row = r.rows[0]
        if (row.expires_at.getTime() <= Date.now()) {
            // Lazy expiry — clear the row so subsequent calls fail fast.
            // Best-effort; the janitor sweep is the authoritative cleaner.
            await this.clear(sessionId).catch(() => undefined)
            return null
        }
        const plain = this.fields.decrypt(row.encrypted_credentials)
        const map = JSON.parse(plain) as CredentialMap
        return map[target] ?? null
    }

    async clear(sessionId: string): Promise<void> {
        await this.pool.query(`DELETE FROM agent_session_credential WHERE session_id = $1`, [sessionId])
    }

    /**
     * Janitor-side sweep: removes all expired rows. Called periodically;
     * the lazy expiry in `resolve` handles individual-row freshness
     * during normal traffic.
     */
    async sweepExpired(): Promise<number> {
        const r = await this.pool.query(`DELETE FROM agent_session_credential WHERE expires_at <= NOW()`)
        return r.rowCount ?? 0
    }
}
