import { Fernet } from 'fernet-nodejs'

/**
 * Marker key used to wrap an inline-encrypted value inside a HogFlow action's inputs.
 * Kept in sync with the Python side (posthog/cdp/hog_flow_inputs.py).
 *
 * Encrypted shape: `{ "__ph_encrypted": "<fernet_token>" }` where the token decrypts to a JSON
 * string representing the original (cleartext) value.
 */
export const INLINE_ENCRYPTED_MARKER = '__ph_encrypted'

export function isInlineEncryptedValue(value: unknown): value is Record<string, string> {
    return (
        typeof value === 'object' &&
        value !== null &&
        typeof (value as Record<string, unknown>)[INLINE_ENCRYPTED_MARKER] === 'string'
    )
}

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
     * Decrypts an inputs dict (as stored on a HogFlow action) by Fernet-decrypting any input
     * whose `value` is an inline-encrypted wrapper. Non-encrypted entries pass through.
     */
    decryptInlineInputs<T extends Record<string, { value?: unknown } & Record<string, unknown>> | null | undefined>(
        inputs: T
    ): T {
        if (!inputs) {
            return inputs
        }
        const result: Record<string, { value?: unknown } & Record<string, unknown>> = {}
        for (const [key, item] of Object.entries(inputs)) {
            if (item && isInlineEncryptedValue(item.value)) {
                const token = item.value[INLINE_ENCRYPTED_MARKER]
                const decryptedJson = this.decrypt(token)
                let decryptedValue: unknown = item.value
                if (typeof decryptedJson === 'string') {
                    try {
                        decryptedValue = JSON.parse(decryptedJson)
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
