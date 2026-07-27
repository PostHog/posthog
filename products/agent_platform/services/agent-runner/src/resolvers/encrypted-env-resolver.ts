/**
 * Default `resolveSecrets` impl for production: read the AgentRevision row,
 * decrypt `encrypted_env` (Django's `EncryptedTextField`), return a plaintext
 * `Record<string, string>`. The runner hands that to
 * `SecretBroker.mintSessionMap()` which nonce-wraps the values for the
 * sandbox.
 *
 * Secrets live on the revision (not the application), so resolving off
 * `session.revision_id` gives each session exactly the secrets its revision
 * was configured with — a draft preview runs against the draft's own secrets,
 * isolated from the live revision by construction. No per-session override
 * needed.
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
        const revision = await deps.revisions.getRevision(session.revision_id)
        return revision?.encrypted_env ? safeDecrypt(deps.encryption, revision.encrypted_env, session) : {}
    }
}

function safeDecrypt(encryption: EncryptedFields, encrypted: string, session: AgentSession): Record<string, string> {
    try {
        return encryption.decryptJsonEnv(encrypted)
    } catch (err) {
        // Don't crash the session — log and continue with empty secrets. The
        // agent will see undefined values and can react accordingly.
        log.error(
            { err: (err as Error).message, session_id: session.id, revision_id: session.revision_id },
            'encrypted_env.decrypt_failed'
        )
        return {}
    }
}
