/**
 * Trigger module interface.
 *
 * Each trigger ships exactly one module — a list of self-describing routes.
 * Every route declares the auth it requires *and* the handler that runs, in
 * the same object. The ingress mounts each route through a guard derived from
 * that `auth` field (see `mount.ts`) and publishes the same field via
 * `GET /agents/<slug>/schemas`. Declared auth and enforced auth are therefore
 * the same data — a route cannot advertise `agent_spec` while its handler
 * forgets to authenticate, which is the class of bug that previously left
 * `/listen` and `/mcp/stream` open.
 *
 * Adding a new trigger:
 *
 *   1. Write `triggers/<name>.ts` exporting a `TriggerModule`.
 *   2. Add the module to `TRIGGER_MODULES` in `routing/server.ts`.
 *   3. Done — guards, schemas, and auth advertisement all cascade from `routes`.
 */

import type { Request, Response } from 'express'
import type { z } from 'zod'

import type {
    ApprovalStore,
    AuthConfig,
    CredentialBroker,
    CredentialMap,
    HttpFetcher,
    IdentityStore,
    SecretResolver,
    SessionEventBus,
    SessionPrincipal,
    SessionQueue,
    Trigger,
} from '@posthog/agent-shared'

import type { AuthProvider, VerifyResult } from '../enqueue/auth'
import type { ResolvedAgent, RevisionResolver, RoutingMode } from '../routing/resolver'

/** Superset of every dep any trigger handler needs. Handlers pick what they use. */
export interface TriggerDeps {
    resolver: RevisionResolver
    queue: SessionQueue
    bus: SessionEventBus
    authProvider?: AuthProvider
    /** Resolves the per-agent Slack signing secret named by `slack.config.signing_secret_ref`. */
    signingSecretResolver: SecretResolver
    identities?: IdentityStore
    /**
     * Approval store — the Slack interactivity handler drives `principal`-type
     * tool-approval decisions through it (markApproving/markRejected + wake) via
     * the shared `applyApprovalDecision` helper. Optional: triggers that never
     * decide approvals ignore it.
     */
    approvals?: ApprovalStore
    /**
     * Per-session credential broker. Chat trigger consumes it on /run + /send;
     * other triggers ignore it. Required — prod wires `PgCredentialBroker`,
     * tests wire the same against the test DB.
     */
    broker: CredentialBroker
    /**
     * Outbound HTTP — the slack trigger consumes it for its bot-token Slack
     * calls (ack reaction, owner-only thread replies). Wired at the ingress
     * entrypoint so the call dispatches through smokescreen in prod alongside
     * every other fetch.
     */
    http?: HttpFetcher
    /** Routing mode + URL inputs the MCP connect-info endpoint advertises. */
    routingMode?: RoutingMode
    domainSuffix?: string
    publicBaseUrl?: string
}

/** Pulled from the `Trigger` discriminator in `@posthog/agent-shared` so this
 *  list can't drift from the spec schema. */
export type TriggerType = Trigger['type']

/**
 * How a route is authenticated. Drives both the guard the route is mounted
 * behind (`mount.ts`) and the shape `/schemas` publishes per agent.
 *
 * - `agent_spec` — the agent's `spec.auth` block. The guard runs `authorize`
 *   and the handler receives an `AuthedRouteCtx` with a guaranteed principal.
 * - `custom` — the agent is resolved and `authConfig` is provided, but the
 *   guard does NOT authorize; the handler calls `ctx.authorize()` itself.
 *   For routes that multiplex several logical operations with different auth
 *   over one HTTP endpoint (MCP's JSON-RPC `/mcp`, where `initialize` is
 *   pre-auth).
 * - `slack_signing` — Slack signature verification on the request body.
 * - `public` — no auth (discovery / healthz-style routes).
 */
export type RouteAuthKind = 'agent_spec' | 'custom' | 'slack_signing' | 'public'

/**
 * Context every route handler receives. The agent is always resolved.
 *
 * `parsed` is the request payload validated against the route's `schema` (body
 * for POST, query for GET) — the mount layer parses + 400s before the handler
 * runs, so handlers read `ctx.parsed` directly instead of re-validating. It's
 * typed via the `P` parameter (set by `defineRoute`); `unknown` for routes that
 * declare no `schema`.
 */
export interface RouteCtx<P = unknown> {
    req: Request
    res: Response
    deps: TriggerDeps
    resolved: ResolvedAgent
    parsed: P
}

/** `agent_spec` routes: the guard authenticated the caller before the handler ran. */
export interface AuthedRouteCtx<P = unknown> extends RouteCtx<P> {
    authConfig: AuthConfig
    principal: SessionPrincipal
    credentials: CredentialMap
}

/** `custom` routes: agent + authConfig resolved; the handler authorizes on demand. */
export interface CustomAuthRouteCtx<P = unknown> extends RouteCtx<P> {
    authConfig: AuthConfig
    /** Run the agent's auth gate (per JSON-RPC method, etc.). */
    authorize(): Promise<VerifyResult>
}

interface RouteCommon {
    method: 'GET' | 'POST'
    /** Path relative to the agent mount (e.g. `/run`, `/slack/events`). */
    path: string
    /**
     * Zod schema for the request payload — body for POST, query for GET. When
     * set, the mount layer validates the payload after auth, responds 400
     * (`{ error: 'invalid_body', issues }`) on failure, and hands the handler a
     * typed `ctx.parsed`. Also published (via `z.toJSONSchema`) on `/schemas`.
     * Use `defineRoute` so `ctx.parsed` is inferred from this schema.
     */
    schema?: z.ZodType
    /** Publish-only JSON Schema, for triggers that parse the body themselves
     *  with a bespoke error contract (MCP JSON-RPC, Slack envelopes). Mutually
     *  exclusive with `schema` — prefer `schema` for plain 400-on-invalid routes. */
    bodySchema?: object
    /** Publish-only JSON Schema for the query string (bespoke-parse GET routes). */
    querySchema?: object
}

/**
 * A route + its auth + its handler, in one object. The `auth` discriminant
 * fixes the context the handler receives, so the type system enforces that an
 * `agent_spec` route reads `ctx.principal` (guaranteed) while a `public` route
 * cannot.
 */
export type TriggerRoute =
    | (RouteCommon & { auth: 'agent_spec'; handler: (ctx: AuthedRouteCtx) => Promise<void> })
    | (RouteCommon & { auth: 'custom'; handler: (ctx: CustomAuthRouteCtx) => Promise<void> })
    | (RouteCommon & { auth: 'slack_signing'; handler: (ctx: RouteCtx) => Promise<void> })
    | (RouteCommon & { auth: 'public'; handler: (ctx: RouteCtx) => Promise<void> })

export interface TriggerModule {
    type: TriggerType
    /** Routes this trigger owns — drives mounting, guards, and `/schemas`. */
    routes: TriggerRoute[]
}

/** The context an `auth` kind yields, carrying the parsed payload type `P`. */
type CtxForAuth<A extends RouteAuthKind, P> = A extends 'agent_spec'
    ? AuthedRouteCtx<P>
    : A extends 'custom'
      ? CustomAuthRouteCtx<P>
      : RouteCtx<P>

/**
 * Define a route, tying its `schema` to the handler's `ctx.parsed` type. The
 * mount layer validates the payload (after auth) and the handler receives it
 * pre-parsed and typed — so a handler can't read an unvalidated body or drift
 * from the declared schema. Omit `schema` for routes with no payload (or for
 * bespoke-parse triggers using `bodySchema`/`querySchema`), in which case
 * `ctx.parsed` is `unknown`.
 */
export function defineRoute<A extends RouteAuthKind, S extends z.ZodType | undefined = undefined>(def: {
    method: 'GET' | 'POST'
    path: string
    auth: A
    schema?: S
    bodySchema?: object
    querySchema?: object
    handler: (ctx: CtxForAuth<A, S extends z.ZodType ? z.infer<S> : unknown>) => Promise<void>
}): TriggerRoute {
    return def as unknown as TriggerRoute
}
