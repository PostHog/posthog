/**
 * Built-in auth verifier impls. The orchestrator in `auth.ts` picks one per
 * request based on the trigger's `auth.modes`. Verifiers are stateless;
 * external dependencies (HTTP introspect, secret lookup) come in via factory
 * args so tests can inject fakes.
 *
 * `posthogVerifier` covers the PostHog identity path — it accepts a bearer
 * (Personal API key today, OAuth later) and validates it against
 * `/api/users/@me/` via the `PosthogIdentityIntrospector`.
 */

import { Request } from 'express'
import { createHmac, timingSafeEqual } from 'node:crypto'

import {
    AgentApplication,
    AuthMode,
    CredentialMap,
    DirectHttpClient,
    HttpFetcher,
    SecretResolver,
    SessionPrincipal,
} from '@posthog/agent-shared'

import { AuthVerifier, publicVerifier, readBearer, VerifyResult } from './auth'

/**
 * Shape returned by PostHog's `/api/users/@me/`. We only depend on the
 * stable fields here so a serializer change in PostHog doesn't break
 * the verifier.
 */
export interface PosthogMeResponse {
    uuid: string
    email: string
    organization?: { id?: string; name?: string }
    team?: { id: number; name?: string; uuid?: string }
    is_staff?: boolean
}

/**
 * The thing that takes a bearer and returns the PostHog user identity.
 * Default impl hits `/api/users/@me/`; tests inject a fake to avoid
 * standing up Django.
 */
export interface PosthogIdentityIntrospector {
    introspect(bearer: string): Promise<PosthogMeResponse | null>
}

export interface DefaultIntrospectorOpts {
    /** Base URL for the PostHog API. Default: `http://localhost:8010`. */
    baseUrl?: string
    /**
     * Outbound HTTP. Production wires a `DirectHttpClient` so the call
     * to PostHog's in-cluster `/api/users/@me/` doesn't get refused by
     * smokescreen as RFC1918. **Never pass the proxy-bound `HttpClient`
     * here** — every authenticated request would 401. Defaults to a
     * fresh `DirectHttpClient` for tests.
     */
    http?: HttpFetcher
}

export function defaultPosthogIntrospector(opts: DefaultIntrospectorOpts = {}): PosthogIdentityIntrospector {
    const baseUrl = (opts.baseUrl ?? 'http://localhost:8010').replace(/\/+$/, '')
    const http = opts.http ?? new DirectHttpClient()
    return {
        async introspect(bearer: string): Promise<PosthogMeResponse | null> {
            const res = await http.fetch(`${baseUrl}/api/users/@me/`, {
                headers: { Authorization: `Bearer ${bearer}`, Accept: 'application/json' },
            })
            if (res.status === 401 || res.status === 403) {
                return null
            }
            if (!res.ok) {
                // Network / 5xx — treat as "couldn't verify", same as invalid.
                return null
            }
            return (await res.json()) as PosthogMeResponse
        },
    }
}

function posthogPrincipalFrom(me: PosthogMeResponse): SessionPrincipal {
    return {
        kind: 'posthog',
        user_id: me.uuid,
        user_uuid: me.uuid,
        team_id: me.team?.id ?? 0,
        email: me.email,
    }
}

/**
 * PostHog credential verifier. Accepts a bearer (Personal API key today, OAuth
 * later) and validates it against `/api/users/@me/`. Produces a `posthog`
 * principal + a `posthog_api` credential for tools.
 *
 * The bearer only proves "is a valid PostHog user somewhere" — it carries no
 * tenant binding of its own. We therefore require the user's active team to
 * match the agent's owning team (`application.team_id`); otherwise any valid
 * bearer from any org would pass a `posthog`-gated agent (cross-team-open).
 */
export function posthogVerifier(introspector: PosthogIdentityIntrospector): AuthVerifier {
    return {
        modeType: 'posthog',
        async verify(req: Request, _mode: AuthMode, application: AgentApplication): Promise<VerifyResult> {
            const bearer = readBearer(req)
            if (!bearer) {
                return { ok: false, status: 0, reason: 'skip' }
            }
            const me = await introspector.introspect(bearer)
            if (!me) {
                return { ok: false, status: 401, reason: 'invalid_token' }
            }
            // Tenant gate: the verified user must belong to the agent's team.
            // `me.team?.id` is the user's active project; a stranger from
            // another org is rejected even with a valid bearer.
            if (me.team?.id !== application.team_id) {
                return { ok: false, status: 403, reason: 'wrong_team' }
            }
            const credentials: CredentialMap = {
                posthog_api: { kind: 'posthog_bearer', token: bearer },
            }
            return { ok: true, principal: posthogPrincipalFrom(me), credentials }
        },
    }
}

/**
 * JWT verifier. Signature is HS256 over the encrypted-env secret named
 * by `mode.issuer_secret_ref`. Standard 3-segment compact JWT format.
 *
 * Keeps the implementation deliberately small (no audience checking,
 * no nbf, no key rotation) — the embedding party owns the secret and
 * the claim shape; we just prove possession.
 */
export interface JwtSecretResolver {
    resolve(secretRef: string, application: AgentApplication): Promise<string | null>
}

export function jwtVerifier(resolver: JwtSecretResolver): AuthVerifier {
    return {
        modeType: 'jwt',
        async verify(req: Request, mode: AuthMode, application: AgentApplication): Promise<VerifyResult> {
            if (mode.type !== 'jwt') {
                return { ok: false, status: 0, reason: 'skip' }
            }
            const bearer = readBearer(req)
            if (!bearer) {
                return { ok: false, status: 0, reason: 'skip' }
            }
            const segments = bearer.split('.')
            if (segments.length !== 3) {
                return { ok: false, status: 401, reason: 'malformed_jwt' }
            }
            const [headerB64, payloadB64, sigB64] = segments
            const secret = await resolver.resolve(mode.issuer_secret_ref, application)
            if (!secret) {
                return { ok: false, status: 500, reason: 'jwt_secret_not_set' }
            }
            const signingInput = `${headerB64}.${payloadB64}`
            const expected = createHmac('sha256', secret).update(signingInput).digest()
            let provided: Buffer
            try {
                provided = Buffer.from(sigB64.replace(/-/g, '+').replace(/_/g, '/'), 'base64')
            } catch {
                return { ok: false, status: 401, reason: 'malformed_jwt_signature' }
            }
            if (provided.length !== expected.length || !timingSafeEqual(provided, expected)) {
                return { ok: false, status: 401, reason: 'invalid_jwt_signature' }
            }
            let header: { alg?: string }
            let claims: Record<string, unknown>
            try {
                header = JSON.parse(
                    Buffer.from(headerB64.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString()
                ) as {
                    alg?: string
                }
                claims = JSON.parse(
                    Buffer.from(payloadB64.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString()
                ) as Record<string, unknown>
            } catch {
                return { ok: false, status: 401, reason: 'malformed_jwt_payload' }
            }
            if (header.alg !== 'HS256') {
                return { ok: false, status: 401, reason: 'unsupported_jwt_alg' }
            }
            const exp = claims.exp
            if (typeof exp === 'number' && exp * 1000 < Date.now()) {
                return { ok: false, status: 401, reason: 'expired_jwt' }
            }
            const sub = claims.sub
            if (typeof sub !== 'string') {
                return { ok: false, status: 401, reason: 'jwt_missing_sub' }
            }
            const principal: SessionPrincipal = {
                kind: 'jwt',
                issuer_secret_ref: mode.issuer_secret_ref,
                sub,
                claims,
            }
            const credentials: CredentialMap = {
                self: { kind: 'jwt', token: bearer, claims },
            }
            return { ok: true, principal, credentials }
        },
    }
}

/** Constant-time string compare that tolerates length mismatch. */
function secretsMatch(provided: string, expected: string): boolean {
    const a = Buffer.from(provided)
    const b = Buffer.from(expected)
    return a.length === b.length && timingSafeEqual(a, b)
}

/**
 * Conventional header a shared-secret caller may send to identify itself
 * behind the shared secret. Lower-cased for Express header lookup. Opt-in:
 * callers that want per-caller session isolation send a stable, unguessable
 * value; everyone else keeps the single-principal behaviour.
 */
export const CALLER_ID_HEADER = 'x-posthog-caller-id'

/**
 * Shared-secret verifier. The header named by the mode carries a secret whose
 * expected value lives in the agent's `encrypted_env` under `mode.secret_ref`.
 * No header → skip; secret unresolvable → fail closed; mismatch → 401.
 */
export function sharedSecretVerifier(resolver: SecretResolver): AuthVerifier {
    return {
        modeType: 'shared_secret',
        async verify(req: Request, mode: AuthMode, application: AgentApplication): Promise<VerifyResult> {
            if (mode.type !== 'shared_secret') {
                return { ok: false, status: 0, reason: 'skip' }
            }
            const provided = req.headers[mode.header.toLowerCase()]
            if (typeof provided !== 'string') {
                return { ok: false, status: 0, reason: 'skip' }
            }
            const expected = await resolver.resolve(mode.secret_ref, application)
            if (!expected) {
                return { ok: false, status: 500, reason: 'shared_secret_not_set' }
            }
            if (!secretsMatch(provided, expected)) {
                return { ok: false, status: 401, reason: 'invalid_secret' }
            }
            // Per-caller identity: the shared secret carries no per-caller
            // identity of its own, so a caller can bind its session to an
            // (unguessable) id via the conventional `x-posthog-caller-id`
            // header. `principalsMatch` then keeps one caller's session
            // scoped to that caller. Absent the header → no discriminator,
            // preserving the single-principal behaviour.
            const callerIdRaw = req.headers[CALLER_ID_HEADER]
            const caller_id = typeof callerIdRaw === 'string' && callerIdRaw.length > 0 ? callerIdRaw : undefined
            const principal: SessionPrincipal = { kind: 'shared_secret', team_id: application.team_id, caller_id }
            return { ok: true, principal, credentials: {} }
        },
    }
}

/**
 * PostHog-internal server-to-server verifier. Matches the `x-posthog-internal`
 * header against the platform's shared internal secret (`AGENT_INTERNAL_SIGNING_KEY`,
 * also held by Django + janitor). No header → skip; mismatch → 403.
 */
export function posthogInternalVerifier(internalSecret: string): AuthVerifier {
    return {
        modeType: 'posthog_internal',
        async verify(req: Request, _mode: AuthMode, application: AgentApplication): Promise<VerifyResult> {
            const provided = req.headers['x-posthog-internal']
            if (typeof provided !== 'string') {
                return { ok: false, status: 0, reason: 'skip' }
            }
            if (!internalSecret) {
                return { ok: false, status: 500, reason: 'internal_secret_not_set' }
            }
            if (!secretsMatch(provided, internalSecret)) {
                return { ok: false, status: 403, reason: 'invalid_internal_header' }
            }
            const principal: SessionPrincipal = { kind: 'posthog_internal', team_id: application.team_id }
            return { ok: true, principal, credentials: {} }
        },
    }
}

/**
 * The complete built-in verifier set — one verifier per `AuthMode` variant.
 * Every dependency is REQUIRED: you cannot build the set without wiring every
 * mode, so a declared auth mode can never silently go unenforced (the bug this
 * whole design closes). A missing secret/resolver fails closed at request time,
 * never opens the gate. `internalSecret` may be empty in dev — the
 * posthog_internal verifier then fails closed.
 */
export function buildDefaultVerifiers(opts: {
    introspector: PosthogIdentityIntrospector
    jwtSecretResolver: JwtSecretResolver
    sharedSecretResolver: SecretResolver
    internalSecret: string
}): AuthVerifier[] {
    return [
        publicVerifier,
        posthogVerifier(opts.introspector),
        jwtVerifier(opts.jwtSecretResolver),
        sharedSecretVerifier(opts.sharedSecretResolver),
        posthogInternalVerifier(opts.internalSecret),
    ]
}
