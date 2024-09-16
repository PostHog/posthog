import * as crypto from 'crypto'
import { Fernet } from 'fernet-nodejs'

import { PluginsServerConfig } from '../types'

export class EncryptedFields {
    private fernets: Fernet[] = []

    constructor(config: PluginsServerConfig) {
        const secretKeys = config.DJANGO_ENCRYPTION_SECRET_KEYS.split(',').filter((key) => key)
        const saltKeys = config.DJANGO_ENCRYPTION_SALT_KEYS.split(',').filter((key) => key)

        if (!secretKeys.length || !saltKeys.length) {
            throw new Error('Encryption keys are not set')
        }

        const keys = saltKeys.flatMap((saltKey) =>
            secretKeys.map((secretKey) => {
                const salt = Buffer.from(saltKey, 'utf-8')
                const key = crypto.pbkdf2Sync(secretKey, salt, 100000, 32, 'sha256')
                return key.toString('base64')
            })
        )
        this.fernets = keys.map((key) => new Fernet(key))
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
