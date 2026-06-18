/**
 * Default `resolveSecrets` impl for production: read the AgentApplication
 * row, decrypt `encrypted_env` (Django's `EncryptedJSONStringField`), return
 * a plaintext `Record<string, string>`. The runner hands that to
 * `SecretBroker.mintSessionMap()` which nonce-wraps the values for the
 * sandbox.
 *
 * Pass an `EncryptedFields` constructed from `ENCRYPTION_SALT_KEYS` (same
 * env var Django reads from). Missing / empty env → returns `{}` so an
 * agent without configured secrets just gets no nonces — no crash.
 */

import { AgentSession, createLogger, EncryptedFields, RevisionStore } from '@posthog/agent-shared'

const log = createLogger('encrypted-env')

export function makeEncryptedEnvResolver(deps: {
    revisions: RevisionStore
    encryption: EncryptedFields
}): (session: AgentSession) => Promise<Record<string, string>> {
    return async (session) => {
        const app = await deps.revisions.getApplication(session.application_id)
        const base = app?.encrypted_env ? safeDecrypt(deps.encryption, app.encrypted_env, session) : {}
        // Preview-mode overlay: if the session row carries an encrypted
        // `preview_secret_override` map, decrypt it and merge on top. Overlay
        // wins per key (the whole point — the author is testing an alternate
        // value), and the merge is per-session so a live session running
        // concurrently against the same application sees nothing from this
        // path. Decryption failures fall back to the base map so a malformed
        // override row can't take down preview sessions wholesale; the live
        // session would never reach this branch.
        if (session.is_preview && session.preview_secret_override) {
            const overlay = safeDecryptOverlay(deps.encryption, session.preview_secret_override, session)
            if (overlay) {
                log.info(
                    {
                        session_id: session.id,
                        application_id: session.application_id,
                        override_keys: Object.keys(overlay).sort(),
                    },
                    'preview_secret_override.applied'
                )
                return { ...base, ...overlay }
            }
        }
        return base
    }
}

function safeDecrypt(encryption: EncryptedFields, encrypted: string, session: AgentSession): Record<string, string> {
    try {
        return encryption.decryptJsonEnv(encrypted)
    } catch (err) {
        log.error(
            { err: (err as Error).message, session_id: session.id, application_id: session.application_id },
            'encrypted_env.decrypt_failed'
        )
        return {}
    }
}

function safeDecryptOverlay(
    encryption: EncryptedFields,
    encrypted: string,
    session: AgentSession
): Record<string, string> | null {
    try {
        return encryption.decryptJsonEnv(encrypted)
    } catch (err) {
        log.error(
            { err: (err as Error).message, session_id: session.id, application_id: session.application_id },
            'preview_secret_override.decrypt_failed'
        )
        return null
    }
}
