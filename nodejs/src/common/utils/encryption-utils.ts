import crypto from 'crypto'
import { Fernet } from 'fernet-nodejs'

const PBKDF2_ITERATIONS = 100_000
const FERNET_KEY_LENGTH = 32

/** Fernet keys are url-safe base64, matching Python's `base64.urlsafe_b64encode`. */
function toFernetKey(bytes: Buffer): string {
    return bytes.toString('base64').replace(/\+/g, '-').replace(/\//g, '_')
}

export class EncryptedFields {
    private fernets: Fernet[] = []

    /**
     * Key derivation matches Django's `EncryptedFieldMixin.keys` exactly, so values are readable
     * across Django, this service, and the integration gateway:
     *   1. Primary: each `ENCRYPTION_SALT_KEYS` entry used directly as 32-byte Fernet key material.
     *   2. Legacy (decrypt-only, appended last so `encrypt` always uses a primary key):
     *      `PBKDF2-HMAC-SHA256(secret, salt, 100k, 32)` for every `secret` in
     *      `[SECRET_KEY, *SECRET_KEY_FALLBACKS]` × every `salt` in `SALT_KEY`.
     *
     * @param encryptionSaltKeys comma-separated primary keys
     * @param legacySecretKeys comma-separated SECRET_KEY(+fallbacks) — optional, decrypt-only
     * @param saltKeys comma-separated SALT_KEY PBKDF2 salts — optional, decrypt-only
     */
    constructor(encryptionSaltKeys: string, legacySecretKeys: string = '', saltKeys: string = '') {
        for (const key of encryptionSaltKeys.split(',').filter((k) => k)) {
            this.fernets.push(new Fernet(toFernetKey(Buffer.from(key, 'utf-8'))))
        }
        const secrets = legacySecretKeys.split(',').filter((k) => k)
        const salts = saltKeys.split(',').filter((k) => k)
        for (const secret of secrets) {
            for (const salt of salts) {
                const derived = crypto.pbkdf2Sync(secret, salt, PBKDF2_ITERATIONS, FERNET_KEY_LENGTH, 'sha256')
                this.fernets.push(new Fernet(toFernetKey(derived)))
            }
        }
    }

    encrypt(value: string): string {
        if (!this.fernets.length) {
            throw new Error('Encryption keys are not set')
        }
        return this.fernets[0].encrypt(value)
    }

    decrypt(value: string, options?: { ignoreDecryptionErrors: boolean }): string | undefined {
        if (!this.fernets.length) {
            throw new Error('Encryption keys are not set')
        }
        let error: Error | undefined
        // Iterate over all keys and try to decrypt the value
        for (const fernet of this.fernets) {
            try {
                return fernet.decrypt(value)
            } catch (e) {
                error = e
            }
        }

        if (options?.ignoreDecryptionErrors) {
            return value
        }

        throw error
    }

    decryptObject(value: any, options?: { ignoreDecryptionErrors: boolean }): any {
        if (typeof value === 'string') {
            return this.decrypt(value, options)
        }

        if (value === null || value === undefined) {
            return value
        }

        if (Array.isArray(value)) {
            return value.map((item) => this.decryptObject(item, options))
        }

        if (typeof value === 'object') {
            return Object.fromEntries(
                Object.entries(value).map(([key, value]) => [key, this.decryptObject(value, options)])
            )
        }

        return value
    }
}
