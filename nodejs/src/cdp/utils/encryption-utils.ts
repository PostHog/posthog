import { Fernet } from 'fernet-nodejs'
import { createHmac } from 'node:crypto'

export class EncryptedFields {
    private fernets: Fernet[] = []
    private signingKeys: string[]

    constructor(encryptionSaltKeys: string) {
        const saltKeys = encryptionSaltKeys.split(',').filter((key) => key)
        this.fernets = saltKeys.map((key) => new Fernet(Buffer.from(key, 'utf-8').toString('base64')))
        this.signingKeys = saltKeys
    }

    // The purpose keeps a signature made for one use from being valid for another.
    sign(purpose: string, value: string): string {
        const [primarySignature] = this.signatures(purpose, value)
        return primarySignature
    }

    // One signature per configured key, so that a value signed before a key rotation still verifies.
    signatures(purpose: string, value: string): string[] {
        if (!this.signingKeys.length) {
            throw new Error('Encryption keys are not set')
        }
        const message = `${purpose.length}:${purpose}:${value}`
        return this.signingKeys.map((key) => createHmac('sha256', key).update(message).digest('hex'))
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
