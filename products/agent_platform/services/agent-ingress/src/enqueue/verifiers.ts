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
    AgentRevision,
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
    /** Every organization the user is a member of — used for `organization`-audience gating. */
    organizations?: Array<{ id?: string; name?: string }>
    team?: { id: number; name?: string; uuid?: string }
    is_staff?: boolean
}

/**
 * The thing that takes a bearer and resolves PostHog access. `introspect`
 * returns the user identity (+ their org memberships); `canAccessTeam` answers
 * the `project`-audience entitlement question by delegating to PostHog's own
 * access control. Default impl hits `/api/users/@me/` and `/api/projects/{id}/`;
 * tests inject a fake to avoid standing up Django.
 */
export interface PosthogIdentityIntrospector {
    introspect(bearer: string): Promise<PosthogMeResponse | null>
    /**
     * Can the bearer's user access `teamId`? Probes a team-scoped endpoint with
     * the caller's bearer — 2xx ⇒ yes (RBAC applied server-side), anything else
     * (401/403/404/5xx) ⇒ no, so the gate fails closed. Used only for
     * `audience: 'project'`.
     */
    canAccessTeam(bearer: string, teamId: number): Promise<boolean>
}

/**
 * Resolves a team (project) id to its owning organization id. Backed by the
 * `posthogDb` pool in production (a tiny `posthog_team` lookup, cached — a
 * team's org never changes); a fake in tests. Used only for
 * `audience: 'organization'`, where the agent's team and the Django DB live in
 * a different database than the ingress's revision store, so a JOIN isn't an
 * option. Returns null when the team is unknown (gate fails closed).
 */
export interface TeamOrgLookup {
    orgForTeam(teamId: number): Promise<string | null>
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
        async canAccessTeam(bearer: string, teamId: number): Promise<boolean> {
            // Reading the project at all requires team access, so Django's
            // permission stack is the oracle: 2xx ⇒ access, any failure (incl.
            // 404, which is what PostHog returns for a project you may not see)
            // ⇒ no access. Fails closed on 5xx / network.
            const res = await http.fetch(`${baseUrl}/api/projects/${teamId}/`, {
                headers: { Authorization: `Bearer ${bearer}`, Accept: 'application/json' },
            })
            return res.ok
        },
    }
}

function posthogPrincipalFrom(me: PosthogMeResponse): SessionPrincipal {
    return {
        kind: 'posthog',
        user_id: me.uuid,
        user_uuid: me.uuid,
        // Best-effort: the user's active project at invocation. Informational
        // only — the `@posthog/*` tools no longer derive their operating
        // project from the principal (the agent supplies an explicit
        // `project_id`), so this is for audit/display, not authorization.
        team_id: me.team?.id ?? 0,
        email: me.email,
    }
}

/**
 * PostHog credential verifier. Accepts a bearer (Personal API key or OAuth
 * access token) and validates it against `/api/users/@me/`. Produces a
 * `posthog` principal + a `posthog_api` credential for tools.
 *
 * The bearer proves "is a valid PostHog user"; it carries no tenant binding,
 * so the agent declares its invocation boundary via `mode.audience`:
 *   - `project` (default): the caller must be able to access the agent's owning
 *     team — delegated to PostHog access control via `canAccessTeam`.
 *   - `organization`: the caller must be a member of the agent's owning org —
 *     `orgForTeam(application.team_id)` ∈ the caller's org memberships.
 * Either way the agent then acts AS the caller: the `@posthog/*` tools call
 * PostHog with this user's bearer against an explicit `project_id`, so RBAC is
 * enforced again at the data layer. (Opening an agent to ANY PostHog user
 * across orgs is intentionally not expressible here yet.)
 */
export function posthogVerifier(introspector: PosthogIdentityIntrospector, teamOrg: TeamOrgLookup): AuthVerifier {
    return {
        modeType: 'posthog',
        async verify(
            req: Request,
            mode: AuthMode,
            application: AgentApplication,
            _revision: AgentRevision
        ): Promise<VerifyResult> {
            if (mode.type !== 'posthog') {
                return { ok: false, status: 0, reason: 'skip' }
            }
            const bearer = readBearer(req)
            if (!bearer) {
                return { ok: false, status: 0, reason: 'skip' }
            }
            const me = await introspector.introspect(bearer)
            if (!me) {
                return { ok: false, status: 401, reason: 'invalid_token' }
            }
            // Tenant gate — who may invoke this agent.
            if (mode.audience === 'organization') {
                const agentOrg = await teamOrg.orgForTeam(application.team_id)
                const callerOrgs = new Set(
                    [me.organization?.id, ...(me.organizations ?? []).map((o) => o.id)].filter(
                        (id): id is string => !!id
                    )
                )
                if (!agentOrg || !callerOrgs.has(agentOrg)) {
                    return { ok: false, status: 403, reason: 'not_in_org' }
                }
            } else {
                // 'project' (default): caller must be entitled to the agent's team.
                const allowed = await introspector.canAccessTeam(bearer, application.team_id)
                if (!allowed) {
                    return { ok: false, status: 403, reason: 'not_in_project' }
                }
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
    resolve(secretRef: string, source: { encrypted_env: string | null }): Promise<string | null>
}

export function jwtVerifier(resolver: JwtSecretResolver): AuthVerifier {
    return {
        modeType: 'jwt',
        async verify(
            req: Request,
            mode: AuthMode,
            _application: AgentApplication,
            revision: AgentRevision
        ): Promise<VerifyResult> {
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
            const secret = await resolver.resolve(mode.issuer_secret_ref, revision)
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
 * Shared-secret verifier. The header named by the mode carries a secret whose
 * expected value lives in the agent's `encrypted_env` under `mode.secret_ref`.
 * No header → skip; secret unresolvable → fail closed; mismatch → 401.
 *
 * One secret == one trust principal. Every holder of the agent's secret is
 * the same principal — there is no per-caller discriminator here because a
 * self-asserted header behind the shared secret is forgeable by any other
 * holder and would create a false security boundary. Agents that need
 * per-caller isolation should use the `jwt` mode (forge-resistant `sub`).
 */
export function sharedSecretVerifier(resolver: SecretResolver): AuthVerifier {
    return {
        modeType: 'shared_secret',
        async verify(
            req: Request,
            mode: AuthMode,
            application: AgentApplication,
            revision: AgentRevision
        ): Promise<VerifyResult> {
            if (mode.type !== 'shared_secret') {
                return { ok: false, status: 0, reason: 'skip' }
            }
            const provided = req.headers[mode.header.toLowerCase()]
            if (typeof provided !== 'string') {
                return { ok: false, status: 0, reason: 'skip' }
            }
            const expected = await resolver.resolve(mode.secret_ref, revision)
            if (!expected) {
                return { ok: false, status: 500, reason: 'shared_secret_not_set' }
            }
            if (!secretsMatch(provided, expected)) {
                return { ok: false, status: 401, reason: 'invalid_secret' }
            }
            const principal: SessionPrincipal = { kind: 'shared_secret', team_id: application.team_id }
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
        async verify(
            req: Request,
            _mode: AuthMode,
            application: AgentApplication,
            _revision: AgentRevision
        ): Promise<VerifyResult> {
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
    teamOrg: TeamOrgLookup
    jwtSecretResolver: JwtSecretResolver
    sharedSecretResolver: SecretResolver
    internalSecret: string
}): AuthVerifier[] {
    return [
        publicVerifier,
        posthogVerifier(opts.introspector, opts.teamOrg),
        jwtVerifier(opts.jwtSecretResolver),
        sharedSecretVerifier(opts.sharedSecretResolver),
        posthogInternalVerifier(opts.internalSecret),
    ]
}
