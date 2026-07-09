/**
 * Resolves a named entry from a source's `encrypted_env` (an `AgentRevision`).
 * Used by the Slack trigger (signing secret, bot token), the jwt + shared_secret
 * auth verifiers, and the runner's failure notifier — anything needing a
 * per-revision secret decrypted at request time.
 */

import { EncryptedFields } from './encryption'

export interface SecretResolver {
    /** Resolve a named entry from the source's `encrypted_env`. Returns null
     *  on missing env, decrypt failure, or absent / empty value. Never throws. */
    resolve(secretKey: string, source: { encrypted_env: string | null }): Promise<string | null>
}

export class EncryptedEnvSecretResolver implements SecretResolver {
    constructor(private readonly encryption: EncryptedFields) {}

    async resolve(secretKey: string, source: { encrypted_env: string | null }): Promise<string | null> {
        if (!source.encrypted_env) {
            return null
        }
        try {
            const env = this.encryption.decryptJsonEnv(source.encrypted_env)
            const value = env[secretKey]
            return typeof value === 'string' && value.length > 0 ? value : null
        } catch {
            return null
        }
    }
}
