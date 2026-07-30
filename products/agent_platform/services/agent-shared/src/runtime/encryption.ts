/**
 * Decrypts fields written by Django's `EncryptedTextField` /
 * `EncryptedJSONStringField`. Ported from v1's
 * `services/agent-core/src/encryption/index.ts` — same key schedule and
 * compatible wire format.
 *
 * `ENCRYPTION_SALT_KEYS` is a comma-separated list of UTF-8 keys. Each is
 * base64-encoded into a Fernet key. On decrypt we try each in order so a
 * key rotation can ship without flushing in-flight encrypted rows: put the
 * new key first, leave the previous key behind it until rewrites complete.
 *
 * Used by the runner to decrypt `AgentApplication.encrypted_env` before
 * resolving secrets into `SecretBroker` for tool dispatch.
 */

import { Fernet } from 'fernet-nodejs'

/**
 * Derive a Fernet key exactly as Django does: urlsafe base64, not standard. If a
 * salt key's base64 contains `+`/`/` the two diverge, `fernet-nodejs` rejects the
 * key, and the runner can't decrypt Django's ciphertext.
 */
function toFernetKey(saltKey: string): string {
    return Buffer.from(saltKey, 'utf-8').toString('base64').replace(/\+/g, '-').replace(/\//g, '_')
}

export class EncryptedFields {
    private readonly fernets: Fernet[]

    /**
     * Throws synchronously if no keys are supplied. Services that need
     * encryption (the credential broker, integrations) construct this at
     * boot, so a misconfigured deploy fails on start rather than at the
     * first encrypt call. Dev gets a deterministic default via `isDev()`
     * in `platform.ts`; prod must set `ENCRYPTION_SALT_KEYS` explicitly.
     */
    constructor(encryptionSaltKeys: string) {
        const keys = encryptionSaltKeys.split(',').filter((k) => k.length > 0)
        if (keys.length === 0) {
            throw new Error('EncryptedFields: no keys configured (set ENCRYPTION_SALT_KEYS to a 32-byte UTF-8 string)')
        }
        this.fernets = keys.map((k) => new Fernet(toFernetKey(k)))
    }

    encrypt(value: string): string {
        return this.fernets[0].encrypt(value)
    }

    /**
     * Try each key in turn. If `ignoreDecryptionErrors` is set, returns the
     * raw input unchanged when no key works (used by lenient call sites that
     * need to tolerate plaintext-bypass for migration). Otherwise throws.
     */
    decrypt(value: string, options?: { ignoreDecryptionErrors?: boolean }): string {
        if (this.fernets.length === 0) {
            throw new Error('EncryptedFields: no keys configured (set ENCRYPTION_SALT_KEYS)')
        }
        let lastErr: Error | undefined
        for (const f of this.fernets) {
            try {
                return f.decrypt(value)
            } catch (err) {
                lastErr = err as Error
            }
        }
        if (options?.ignoreDecryptionErrors) {
            return value
        }
        throw lastErr ?? new Error('EncryptedFields: decryption failed')
    }

    /**
     * Decrypt a JSON-encoded env block (Django's `EncryptedJSONStringField`).
     * Returns `{}` for an empty / unset value so callers don't have to special-case.
     */
    decryptJsonEnv(value: string | null | undefined): Record<string, string> {
        if (!value) {
            return {}
        }
        const plain = this.decrypt(value)
        const parsed = JSON.parse(plain)
        if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
            throw new Error('EncryptedFields.decryptJsonEnv: decoded value is not a JSON object')
        }
        const out: Record<string, string> = {}
        for (const [k, v] of Object.entries(parsed)) {
            out[k] = String(v)
        }
        return out
    }

    /**
     * Decrypt a Django `EncryptedJSONField` value without forcing values to
     * strings. `EncryptedJSONField` stores the column as TEXT (per
     * `EncryptedFieldMixin.get_internal_type`) so the wire format is
     * identical to `EncryptedTextField`; only the Python-side type is
     * different. Returns `null` on empty input. Throws if the decoded value
     * isn't a JSON object.
     */
    decryptJson(value: string | null | undefined): Record<string, unknown> | null {
        if (!value) {
            return null
        }
        const plain = this.decrypt(value)
        const parsed = JSON.parse(plain)
        if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
            throw new Error('EncryptedFields.decryptJson: decoded value is not a JSON object')
        }
        return parsed as Record<string, unknown>
    }

    /**
     * Decrypt a Django `EncryptedJSONField` (RECURSIVE per-leaf — not the
     * whole-blob `decryptJson`). Structure stays plaintext JSON; each scalar leaf
     * was `encrypt(str(value))`, so leaves come back as STRINGS (`3600`→"3600",
     * `True`→"True"); `null` passes through. Pass the parsed value (node-pg parses
     * jsonb; JSON.parse a text column first). Mirrors `_decrypt_values`.
     */
    decryptJsonFieldValue(value: unknown): unknown {
        if (value === null || value === undefined) {
            return value
        }
        if (Array.isArray(value)) {
            return value.map((v) => this.decryptJsonFieldValue(v))
        }
        if (typeof value === 'object') {
            const out: Record<string, unknown> = {}
            for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
                out[k] = this.decryptJsonFieldValue(v)
            }
            return out
        }
        if (typeof value === 'string') {
            return this.decrypt(value)
        }
        // Numbers/booleans shouldn't appear at rest (they were str()-ified then
        // encrypted to a string token), but pass them through if they do.
        return value
    }

    /**
     * Inverse of `decryptJsonFieldValue` for write-back. Mirrors `_encrypt_values`:
     * each scalar leaf is `str(value)`-ified (bool → "True"/"False") then
     * encrypted; `null` preserved. `JSON.stringify` the result for the column.
     */
    encryptJsonFieldValue(value: unknown): unknown {
        if (value === null || value === undefined) {
            return value
        }
        if (Array.isArray(value)) {
            return value.map((v) => this.encryptJsonFieldValue(v))
        }
        if (typeof value === 'object') {
            const out: Record<string, unknown> = {}
            for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
                out[k] = this.encryptJsonFieldValue(v)
            }
            return out
        }
        return this.encrypt(typeof value === 'boolean' ? (value ? 'True' : 'False') : String(value))
    }
}
