import { Fernet } from 'fernet-nodejs'

import { PluginsServerConfig } from '../types'

export class EncryptedFields {
    private fernets: Fernet[] = []

    constructor(config: PluginsServerConfig) {
        const saltKeys = config.DJANGO_ENCRYPTION_SALT_KEYS.split(',').filter((key) => key)

        if (!saltKeys.length) {
            throw new Error('Encryption keys are not set')
        }

        this.fernets = saltKeys.map((key) => new Fernet(key))
    }

    encrypt(value: string): string {
        return this.fernets[0].encrypt(value)
    }

    decrypt(value: string): string | undefined {
        let error: Error | undefined
        // Iterate over all keys and try to decrypt the value
        for (const fernet of this.fernets) {
            try {
                return fernet.decrypt(value)
            } catch (e) {
                error = e
            }
        }

        throw error
    }
}
