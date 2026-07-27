/**
 * Test-side auth helpers. Most existing cases want "this PAT is valid,
 * this internal secret is valid, this shared secret is valid" with no
 * external Django; this module gives them a stub provider + matching
 * spec snippets so the migration to the new multi-mode shape stays a
 * one-liner per test.
 */

import {
    type AuthProvider,
    type AuthVerifier,
    type VerifyResult,
    publicVerifier,
    readBearer,
} from '@posthog/agent-ingress'
import type { CredentialMap, SessionPrincipal } from '@posthog/agent-shared'

export interface FakeTokens {
    /** Bearer that resolves to a posthog user (the `posthog` auth mode). */
    posthog?: string
    /** x-posthog-internal value. */
    internal?: string
    /** Shared-secret value (in the header named per spec). */
    shared?: string
}

/**
 * Build the standard fixture auth provider — accepts whichever tokens
 * the caller specifies. Returns a posthog user principal for the `posthog`
 * mode, internal/shared_secret principals for the others.
 */
export function fakeAuthProvider(opts: FakeTokens & { teamId?: number; userId?: string } = {}): AuthProvider {
    const teamId = opts.teamId ?? 1
    const userId = opts.userId ?? 'user-1'

    const okPosthog = (): VerifyResult => ({
        ok: true,
        principal: { kind: 'posthog', user_id: userId, team_id: teamId, email: `${userId}@test` },
        credentials: { posthog_api: { kind: 'posthog_bearer', token: opts.posthog ?? '' } } as CredentialMap,
    })

    const verifiers: AuthVerifier[] = [publicVerifier]

    if (opts.posthog) {
        verifiers.push({
            modeType: 'posthog',
            async verify(req) {
                const bearer = readBearer(req)
                if (!bearer) {
                    return { ok: false, status: 0, reason: 'skip' }
                }
                if (bearer !== opts.posthog) {
                    return { ok: false, status: 401, reason: 'invalid_token' }
                }
                return okPosthog()
            },
        })
    }

    if (opts.internal) {
        verifiers.push({
            modeType: 'posthog_internal',
            async verify(req) {
                const header = req.headers['x-posthog-internal']
                if (typeof header !== 'string') {
                    return { ok: false, status: 0, reason: 'skip' }
                }
                if (header !== opts.internal) {
                    return { ok: false, status: 403, reason: 'invalid_internal_header' }
                }
                const principal: SessionPrincipal = { kind: 'posthog_internal', team_id: teamId }
                return { ok: true, principal, credentials: {} }
            },
        })
    }

    if (opts.shared) {
        verifiers.push({
            modeType: 'shared_secret',
            async verify(req, mode) {
                if (mode.type !== 'shared_secret') {
                    return { ok: false, status: 0, reason: 'skip' }
                }
                const value = req.headers[mode.header.toLowerCase()]
                if (typeof value !== 'string') {
                    return { ok: false, status: 0, reason: 'skip' }
                }
                if (value !== opts.shared) {
                    return { ok: false, status: 401, reason: 'invalid_secret' }
                }
                const principal: SessionPrincipal = { kind: 'shared_secret', team_id: teamId }
                return { ok: true, principal, credentials: {} }
            },
        })
    }

    return { verifiers }
}
