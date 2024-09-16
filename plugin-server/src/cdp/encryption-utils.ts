import * as crypto from 'crypto'

import { PluginsServerConfig } from '../types'

export class EncryptedFields {
    private keys: string[] = []
    private cyphers: crypto.Cipher[] = []

    constructor(config: PluginsServerConfig) {
        const secretKeys = config.DJANGO_ENCRYPTION_SECRET_KEYS.split(',')
        const saltKeys = config.DJANGO_ENCRYPTION_SALT_KEYS.split(',')

        if (!secretKeys.length || !saltKeys.length) {
            throw new Error('Encryption keys are not set')
        }

        this.keys = saltKeys.flatMap((saltKey) =>
            secretKeys.map((secretKey) => {
                const salt = Buffer.from(saltKey, 'utf-8')
                const key = crypto.pbkdf2Sync(secretKey, salt, 100000, 32, 'sha256')
                return key.toString('base64')
            })
        )
        this.cyphers = this.keys.map((key) =>
            crypto.createCipheriv('aes-256-cbc', Buffer.from(key, 'base64'), Buffer.alloc(16, 0))
        )
    }

    encrypt(value: string): string {
        const cypher = this.cyphers[0]
        const encrypted = cypher.update(value, 'utf8', 'base64') + cypher.final('base64')
        return encrypted
    }

    decrypt(value: string): string | undefined {
        let error: Error | undefined
        // Iterate over all keys and try to decrypt the value
        for (const cypher of this.cyphers) {
            try {
                const decrypted = cypher.update(value, 'base64', 'utf8') + cypher.final('utf8')
                return decrypted
            } catch (e) {
                error = e
            }
        }

        throw error
    }
}
