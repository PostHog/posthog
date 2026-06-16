/**
 * Resolves a named entry from an agent's `AgentApplication.encrypted_env`.
 * Used by the Slack trigger (signing secret, bot token), the shared_secret auth
 * verifier, and the runner's failure notifier — anything needing a per-agent
 * secret decrypted at request time.
 */

import { AgentApplication } from '../spec/spec'
import { EncryptedFields } from './encryption'

export interface SecretResolver {
    /** Resolve a named entry from the application's `encrypted_env`. Returns null
     *  on missing env, decrypt failure, or absent / empty value. Never throws. */
    resolve(secretKey: string, application: AgentApplication): Promise<string | null>
}

export class EncryptedEnvSecretResolver implements SecretResolver {
    constructor(private readonly encryption: EncryptedFields) {}

    async resolve(secretKey: string, application: AgentApplication): Promise<string | null> {
        if (!application.encrypted_env) {
            return null
        }
        try {
            const env = this.encryption.decryptJsonEnv(application.encrypted_env)
            const value = env[secretKey]
            return typeof value === 'string' && value.length > 0 ? value : null
        } catch {
            return null
        }
    }
}
