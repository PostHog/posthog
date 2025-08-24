import { Fernet } from 'fernet-nodejs'

import { PluginsServerConfig } from '../../types'

export class EncryptedFields {
    private fernets: Fernet[] = []

    constructor(config: PluginsServerConfig) {
        const saltKeys = config.ENCRYPTION_SALT_KEYS.split(',').filter((key) => key)

        if (!saltKeys.length) {
            throw new Error('Encryption keys are not set')
        }

        this.fernets = saltKeys.map((key) => new Fernet(Buffer.from(key, 'utf-8').toString('base64')))
    }

    encrypt(value: string): string {
        return this.fernets[0].encrypt(value)
    }

    decrypt(value: string, options?: { ignoreDecryptionErrors: boolean }): string | undefined {
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
