import { Fernet } from 'fernet-nodejs'

import { parseJSON } from '../../utils/json-parse'

export class EncryptedFields {
    private fernets: Fernet[] = []

    constructor(encryptionSaltKeys: string) {
        const saltKeys = encryptionSaltKeys.split(',').filter((key) => key)
        this.fernets = saltKeys.map((key) => new Fernet(Buffer.from(key, 'utf-8').toString('base64')))
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

    /**
     * Decrypts an inputs dict (as stored on a HogFlow action) by Fernet-decrypting the value
     * of any input whose schema entry is flagged `secret: true`. Non-secret entries pass
     * through untouched, mirroring the Python write-side rule in
     * `posthog/cdp/hog_flow_inputs.py`.
     *
     * The schema is the sole signal for "this value is encrypted" — there is no in-band marker.
     * A schema-flagged secret value that fails to decrypt (legacy plaintext, key rotation gap,
     * or simply not ciphertext) is left as-is rather than raising, so a stale row can't crash
     * a workflow on execution.
     */
    decryptInlineInputs<T extends Record<string, { value?: unknown } & Record<string, unknown>> | null | undefined>(
        inputs: T,
        inputs_schema: ReadonlyArray<{ key: string; secret?: boolean }> | null | undefined
    ): T {
        if (!inputs) {
            return inputs
        }
        const secretKeys = new Set<string>()
        for (const schema of inputs_schema ?? []) {
            if (schema?.secret && schema.key) {
                secretKeys.add(schema.key)
            }
        }
        const result: Record<string, { value?: unknown } & Record<string, unknown>> = {}
        for (const [key, item] of Object.entries(inputs)) {
            if (item && secretKeys.has(key) && typeof item.value === 'string') {
                let decryptedJson: string | undefined
                try {
                    decryptedJson = this.decrypt(item.value)
                } catch {
                    // Not ciphertext (or wrong key) — leave the value alone. The hog runtime
                    // will see whatever was stored, which for a properly-encrypted row would
                    // never reach this branch.
                    result[key] = item
                    continue
                }
                let decryptedValue: unknown = item.value
                if (typeof decryptedJson === 'string') {
                    try {
                        decryptedValue = parseJSON(decryptedJson)
                    } catch {
                        decryptedValue = decryptedJson
                    }
                }
                result[key] = { ...item, value: decryptedValue }
            } else {
                result[key] = item
            }
        }
        return result as T
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
