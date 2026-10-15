import { Fernet } from 'fernet-nodejs'
import { createHmac } from 'node:crypto'

export class EncryptedFields {
    private fernets: Fernet[] = []
    private signingKey: string | undefined

    constructor(encryptionSaltKeys: string) {
        const saltKeys = encryptionSaltKeys.split(',').filter((key) => key)
        this.fernets = saltKeys.map((key) => new Fernet(Buffer.from(key, 'utf-8').toString('base64')))
        this.signingKey = saltKeys[0]
    }

    sign(value: string): string {
        if (!this.signingKey) {
            throw new Error('Encryption keys are not set')
        }
        return createHmac('sha256', this.signingKey).update(value).digest('hex')
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
