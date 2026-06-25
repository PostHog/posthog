/**
 * Per-trigger auth gate. Reads `spec.auth.modes[]` and walks them in
 * order; the first verifier that matches the incoming request wins.
 *
 * **Identity / credentials split** — the verifier produces:
 *
 *   - `principal: SessionPrincipal` — identity-only, persisted on the
 *     session row (used by ACL + audit log)
 *   - `credentials: CredentialMap` — auth materials (bearer tokens, JWT,
 *     claims) keyed by target — written to the `CredentialBroker` for
 *     tools to query at call time. **Never persisted on the session row
 *     or the principal.**
 *
 * Verifiers per mode:
 *
 *   - `public`             — always succeeds, anonymous principal, no creds
 *   - `posthog`            — Authorization: Bearer <token> (PAT today, OAuth
 *                            later); verified via an `IdentityIntrospector`
 *                            (PostHog: hit `/api/users/@me/`); produces
 *                            `posthog` principal + `posthog_api` credential
 *   - `jwt`                — Authorization: Bearer <jwt>; signature
 *                            verified with the agent's encrypted-env
 *                            secret referenced by `issuer_secret_ref`;
 *                            produces `jwt` principal + `self` credential
 *   - `shared_secret`      — header bearer; matched by per-agent secret
 *   - `posthog_internal`   — x-posthog-internal header; legacy server-to-
 *                            server pathway used by Django ↔ ingress
 *
 * Adding a new mode is two steps: extend `AuthModeSchema` in agent-shared,
 * add a verifier here, register it in `buildDefaultVerifiers`.
 */

import { Request } from 'express'

import {
    AgentApplication,
    AgentRevision,
    AuthConfig,
    AuthMode,
    AuthModeType,
    CredentialMap,
    SessionPrincipal,
} from '@posthog/agent-shared'

// `principalsMatch` lives in `@posthog/agent-shared` (PR 7) so the runner's
// per-asker approval shortcut can use the same exact comparison the ingress
// edge uses. Re-exported here to keep the local import surface unchanged for
// the file's existing consumers (acl.ts, triggers/mcp.ts).
export { principalsMatch } from '@posthog/agent-shared'

export interface VerifyOk {
    ok: true
    principal: SessionPrincipal
    credentials: CredentialMap
}
export interface VerifyFail {
    ok: false
    status: number
    reason: string
}
export type VerifyResult = VerifyOk | VerifyFail

/**
 * One verifier per auth mode type. The verifier is responsible for
 * extracting any necessary inputs from `req` (header, body, etc.),
 * cross-checking against the `application` (e.g. team-scoping) +
 * `mode` (mode-specific config), and returning identity + credentials.
 *
 * Verifiers must return `ok: false` for both "no input present" (so
 * fallback to another mode is possible) and "input present but invalid"
 * (auth genuinely failed). The orchestrator distinguishes via status
 * codes: 401/403 are "invalid", anything else is "skip".
 *
 * To allow fallback to the next configured mode on a soft miss
 * (request didn't carry the right header at all), return
 * `{ ok: false, status: 0, reason: 'skip' }`.
 */
export interface AuthVerifier {
    readonly modeType: AuthModeType
    verify(req: Request, mode: AuthMode, application: AgentApplication, revision: AgentRevision): Promise<VerifyResult>
}

export interface AuthProvider {
    verifiers: AuthVerifier[]
}

/**
 * Public verifier — succeeds with the anonymous principal, but ONLY for an
 * explicitly `public`-typed mode (which the schema forces to carry
 * `acknowledge_public_exposure: true`). The mode-type guard means anonymous
 * pass-through can never happen by accident — a mis-wired or malformed mode
 * falls through to the next, and an agent with no `public` mode fails closed.
 * Order matters: when `public` is listed, every request matches it, so other
 * modes only get a chance if they're listed first.
 */
export const publicVerifier: AuthVerifier = {
    modeType: 'public',
    async verify(_req, mode) {
        if (mode.type !== 'public') {
            return { ok: false, status: 0, reason: 'skip' }
        }
        return { ok: true, principal: { kind: 'anonymous' }, credentials: {} }
    },
}

/**
 * Default no-op provider. Test harnesses + dev environments should
 * inject a real provider. With no verifiers registered, every auth
 * mode falls through and the trigger 401s — keeping the platform
 * fail-closed by default.
 */
export const PUBLIC_ONLY_AUTH_PROVIDER: AuthProvider = {
    verifiers: [publicVerifier],
}

/**
 * Extract the Bearer token from the Authorization header, falling back to
 * the `?token=` query param. Returns null when neither carries a token (let
 * the caller fall through to the next mode).
 *
 * The query fallback exists for browser `EventSource` (GET /listen SSE):
 * the EventSource API can't set request headers, so the bearer has to ride
 * in the URL — the same constraint that drives the `?preview_token=` fallback
 * in resolve.ts. The header always wins; tokens in URLs land in access logs,
 * so non-SSE clients should keep using the header.
 */
export function readBearer(req: Request): string | null {
    const header = req.headers['authorization']
    if (typeof header === 'string' && header.startsWith('Bearer ')) {
        const token = header.slice('Bearer '.length).trim()
        if (token.length > 0) {
            return token
        }
    }
    const queryToken = req.query?.token
    if (typeof queryToken === 'string' && queryToken.trim().length > 0) {
        return queryToken.trim()
    }
    return null
}

/**
 * Walk the spec's configured auth modes; first verifier whose mode is
 * configured AND verifies the request wins. Verifiers return `status: 0`
 * for "no relevant input here, try the next mode"; non-zero failures
 * short-circuit (a present-but-invalid bearer doesn't fall through to
 * the next mode — that'd be a security hole).
 */
export async function authorize(
    req: Request,
    application: AgentApplication,
    revision: AgentRevision,
    authConfig: AuthConfig,
    provider: AuthProvider
): Promise<VerifyResult> {
    const modes = authConfig.modes
    if (modes.length === 0) {
        return { ok: false, status: 401, reason: 'no_modes_configured' }
    }
    let firstHardFailure: VerifyFail | null = null
    for (const mode of modes) {
        const verifier = provider.verifiers.find((v) => v.modeType === mode.type)
        if (!verifier) {
            continue
        }
        const result = await verifier.verify(req, mode, application, revision)
        if (result.ok) {
            return result
        }
        // status === 0 means "skip"; anything else is a real failure
        // worth surfacing if no later mode matches.
        if (result.status !== 0 && !firstHardFailure) {
            firstHardFailure = result
        }
    }
    if (firstHardFailure) {
        return firstHardFailure
    }
    return { ok: false, status: 401, reason: 'no_matching_mode' }
}
