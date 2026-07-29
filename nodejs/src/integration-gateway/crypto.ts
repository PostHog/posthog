import crypto from 'crypto'
import { Fernet } from 'fernet-nodejs'

import { logger } from '~/common/utils/logger'

/**
 * Fernet decryptor, wire-compatible with Django's `EncryptedJSONField`
 * (`posthog/helpers/encrypted_fields.py`).
 *
 * Key derivation must match `EncryptedFieldMixin.keys` EXACTLY — a mismatch fails to decrypt
 * silently in prod:
 *   1. Primary: `urlsafe_b64(k)` for each `k` in `ENCRYPTION_SALT_KEYS` (each is 32 raw bytes).
 *   2. Legacy (decrypt-only, appended last): `urlsafe_b64(PBKDF2-HMAC-SHA256(secret, salt, 100k, 32))`
 *      for every `secret` in `[SECRET_KEY, *SECRET_KEY_FALLBACKS]` × every `salt` in `SALT_KEY`.
 *
 * `MultiFernet` semantics: decrypt tries every key (newest first), so both salt-key and legacy
 * ciphertext decrypt; encrypt always uses the primary key so Django can read what we write back.
 */

const PBKDF2_ITERATIONS = 100_000
const FERNET_KEY_LEN = 32

/**
 * Fernet keys are url-safe base64 (with padding), matching Python's `base64.urlsafe_b64encode`.
 */
function toFernetKey(bytes: Buffer): string {
    return bytes.toString('base64').replace(/\+/g, '-').replace(/\//g, '_')
}

export class IntegrationDecryptor {
    private fernets: Fernet[] = []
    public readonly primaryKeyCount: number
    public readonly legacyKeyCount: number

    /**
     * Build the decryptor from the same inputs Django uses. Fails fast if no valid primary key is
     * built — the service must never run decrypt-only, mirroring the Django/Rust intent that new
     * values are always encryptable under a primary key.
     */
    constructor(encryptionSaltKeys: string[], legacySecretKeys: string[], saltKeys: string[]) {
        for (const key of encryptionSaltKeys) {
            try {
                this.fernets.push(new Fernet(toFernetKey(Buffer.from(key, 'utf-8'))))
            } catch {
                logger.warn(
                    '[IntegrationDecryptor] ENCRYPTION_SALT_KEYS entry is not a valid 32-byte Fernet key; skipping it'
                )
            }
        }
        this.primaryKeyCount = this.fernets.length
        if (this.primaryKeyCount === 0) {
            throw new Error(
                'no usable primary decryption keys (ENCRYPTION_SALT_KEYS is empty or every entry is not 32 bytes)'
            )
        }

        // Legacy keys, appended last so they are only ever used as decrypt fallbacks.
        for (const secret of legacySecretKeys) {
            for (const salt of saltKeys) {
                const derived = crypto.pbkdf2Sync(secret, salt, PBKDF2_ITERATIONS, FERNET_KEY_LEN, 'sha256')
                try {
                    this.fernets.push(new Fernet(toFernetKey(derived)))
                } catch {
                    // A derived key should always be valid; skip defensively rather than crash.
                }
            }
        }
        this.legacyKeyCount = this.fernets.length - this.primaryKeyCount
    }

    /**
     * Decrypt one Fernet token. Returns `undefined` when no key can decrypt it. Callers treat that
     * as pass-through, matching Django's `ignore_decrypt_errors=True` on `sensitive_config`.
     */
    decryptLeaf(token: string): string | undefined {
        for (const fernet of this.fernets) {
            try {
                return fernet.decrypt(token)
            } catch {
                // Try the next key.
            }
        }
        return undefined
    }

    /**
     * Encrypt one value under the PRIMARY key (matching Django's write path), producing a standard
     * Fernet token Django can decrypt. Used by the token-refresh writer for rotated tokens.
     */
    encryptLeaf(plaintext: string): string {
        return this.fernets[0].encrypt(plaintext)
    }

    /**
     * Recursively decrypt a `sensitive_config` value. Every string leaf is an independent Fernet
     * token; an undecryptable string passes through unchanged; non-string scalars and nulls pass
     * through. Mirrors `EncryptedJSONField._decrypt_values` + `ignore_decrypt_errors=True`.
     */
    decryptSensitiveConfig(value: any): any {
        if (typeof value === 'string') {
            return this.decryptLeaf(value) ?? value
        }
        if (value === null || value === undefined) {
            return value
        }
        if (Array.isArray(value)) {
            return value.map((item) => this.decryptSensitiveConfig(item))
        }
        if (typeof value === 'object') {
            return Object.fromEntries(
                Object.entries(value).map(([key, val]) => [key, this.decryptSensitiveConfig(val)])
            )
        }
        return value
    }
}
