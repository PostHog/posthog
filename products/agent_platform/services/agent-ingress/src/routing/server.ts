/**
 * Boot the ingress as a single Express app. The route table is one block —
 * triggers are siblings under the same /agents/<slug> prefix in path mode, or
 * mounted at root in domain mode.
 */

import express, { Express, Request, Response } from 'express'
import { z } from 'zod'

import type {
    AgentApplication,
    AgentRevision,
    ApprovalStore,
    EncryptedFields,
    IdentityCredentialStore,
    IdentityLinkStateStore,
    IdentityStore,
    SecretResolver,
} from '@posthog/agent-shared'
import {
    applyApprovalDecision,
    buildIdentityRegistry,
    createLogger,
    effectiveApprovalType,
    handleMetricsRequest,
    isDev,
    RevisionStore,
    serializeApprovalRequest,
    type SessionPrincipal,
    SessionQueue,
    triggerAuthConfig,
} from '@posthog/agent-shared'

const log = createLogger('ingress')

import { SessionEventBus } from '@posthog/agent-shared'
import type { AuthConfig } from '@posthog/agent-shared'

import { authorize, AuthProvider, principalsMatch, PUBLIC_ONLY_AUTH_PROVIDER } from '../enqueue/auth'
import { chatTrigger } from '../triggers/chat'
import { mcpTrigger } from '../triggers/mcp'
import { mountTrigger } from '../triggers/mount'
import { resolveAgent } from '../triggers/resolve'
import { slackTrigger } from '../triggers/slack'
import type { RouteAuthKind, TriggerModule } from '../triggers/types'
import { webhookTrigger } from '../triggers/webhook'
import { asyncHandler, errorHandler, httpMetricsMiddleware, requestLogger } from './http-utils'
import { RevisionResolver, RoutingMode } from './resolver'

/**
 * The full set of trigger modules the ingress knows about. Each module is
 * self-describing — its `routes` drive mounting (via `mountTrigger`), the
 * `/schemas` response, and the per-route auth guard. Adding a new trigger
 * means writing one module file and dropping it in this array. Exported so
 * the auth contract test can assert every declared route enforces its `auth`.
 */
export const TRIGGER_MODULES: TriggerModule[] = [chatTrigger, slackTrigger, webhookTrigger, mcpTrigger]

/**
 * Fallback resolver used when callers (mostly dev / harness paths) don't wire
 * a real one. Slack requests under such a setup get a clean
 * `signing_secret_unresolved` 500 instead of an obscure `Cannot read
 * properties of undefined`. Production wires a real `EncryptedFields`-backed
 * resolver — see services/agent-ingress/src/index.ts.
 */
const UNCONFIGURED_SLACK_SIGNING_SECRET_RESOLVER: SecretResolver = {
    async resolve(): Promise<string | null> {
        return null
    },
}

/**
 * Translate a route's auth kind into the concrete shape we publish to
 * callers. Resolved per-agent so the response says, e.g., "this route needs
 * a PAT" or "shared_secret in X-Acme-Secret header" — not just "uses agent
 * auth, look it up yourself."
 */
function resolveRouteAuth(kind: RouteAuthKind, triggerAuth: AuthConfig | null): Record<string, unknown> {
    if (kind === 'public') {
        return { mode: 'public' }
    }
    if (kind === 'slack_signing') {
        return { mode: 'slack_signing', header: 'X-Slack-Signature' }
    }
    // agent_spec — expose the trigger's accepted modes verbatim. Each mode is an
    // already-discriminated `{type, ...}` object; clients introspect to
    // pick a header / token shape they can send.
    return { modes: triggerAuth?.modes ?? [] }
}

export interface BuildAppOpts {
    revisions: RevisionStore
    queue: SessionQueue
    bus: SessionEventBus
    routingMode: RoutingMode
    domainSuffix?: string
    pathPrefix?: string
    /** Path-mode public base URL the MCP connect-info endpoint advertises
     *  (`<publicBaseUrl>/agents/<slug>/mcp`). Ignored in domain mode. */
    publicBaseUrl?: string
    /**
     * Resolves the Slack signing secret named by `slack.config.signing_secret_ref`
     * on the agent's spec. In production: pulls the entry from the agent's
     * `encrypted_env` via `EncryptedFields`. Optional only because chat/
     * webhook/mcp ignore it; if the spec configures a slack trigger and this
     * is absent, the slack trigger boots but every request 500s on
     * `signing_secret_unresolved`.
     */
    slackSigningSecretResolver?: SecretResolver
    authProvider?: AuthProvider
    /** Optional identity store — Slack trigger uses this to mint stable AgentUser ids. */
    identities?: IdentityStore
    /**
     * Approval store — backs the principal-decision surfaces (the Slack
     * interactivity handler today; the `POST /approvals/:id/decide` route).
     * Wired in prod from the agent DB pool; omitted in tests that don't exercise
     * approvals.
     */
    approvals?: ApprovalStore
    /**
     * Shared HMAC signing key with Django for the preview-proxy gate on
     * non-live revision invokes (aud = `agent-ingress.preview`). When
     * unset, the gate is bypassed (dev / harness).
     */
    internalSigningKey?: string
    /**
     * Per-session credential broker. Ingress writes user auth materials
     * (OAuth bearer, PAT, JWT) here at /run + /send; the runner reads
     * via `ToolContext.credentials.resolve(target)`. Required — prod wires
     * `PgCredentialBroker`, tests wire the same against the test DB. No
     * in-memory fallback (it silently lost creds on worker restart).
     */
    credentialBroker: import('@posthog/agent-shared').CredentialBroker
    /**
     * Outbound HTTP for a trigger's outbound calls (the slack trigger's
     * bot-token Slack calls). Wired at the ingress entrypoint from
     * `config.httpsProxy` so the call dispatches through smokescreen in
     * prod. Optional — falls back to a direct HttpClient in tests.
     */
    http?: import('@posthog/agent-shared').HttpFetcher
    /**
     * Identity-linking stores + env decryptor. When all three are wired, the
     * ingress serves `GET /link/:provider/callback`: it consumes the OAuth
     * link-state row, rebuilds the provider from the app's spec + decrypted
     * encrypted_env, and persists the credential. Optional — omitted in tests
     * that don't exercise the callback.
     */
    identityCredentials?: IdentityCredentialStore
    identityLinks?: IdentityLinkStateStore
    envEncryption?: EncryptedFields
    /** PostHog API base — the `{kind:posthog}` provider builds its OAuth
     *  endpoints from this in the link callback. Without it the callback can't
     *  rebuild the posthog provider ("Unknown provider"). */
    posthogApiBaseUrl?: string
}

/**
 * Authenticate an approval-decision request as it would have been authenticated
 * at the originating trigger: walk the agent's chat/mcp trigger auth configs
 * (the surfaces that mint posthog/jwt principals) and return the first verified
 * principal. Null when no configured mode authenticates the request.
 *
 * Returning the FIRST verifying mode is intentional: which configured mode
 * authenticated the request doesn't matter for safety, because the caller still
 * runs `principalsMatch` against the session's own principal — that match is the
 * gate. A credential only verifies against the mode that actually accepts it (a
 * JWT won't pass posthog `/@me`, a PAT isn't a valid JWT, …), so the resolved
 * principal is the genuine caller regardless of trigger iteration order.
 */
async function authenticatePrincipalDecider(
    req: Request,
    application: AgentApplication,
    revision: AgentRevision,
    provider: AuthProvider
): Promise<SessionPrincipal | null> {
    for (const trigger of revision.spec.triggers) {
        if (trigger.type !== 'chat' && trigger.type !== 'mcp') {
            continue
        }
        const authConfig = triggerAuthConfig(trigger)
        if (!authConfig) {
            continue
        }
        const result = await authorize(req, application, revision, authConfig, provider)
        if (result.ok) {
            return result.principal
        }
    }
    return null
}

/**
 * A real, identifiable caller — not the shared `anonymous` principal a
 * public-auth agent hands every caller. `principalsMatch` treats all anonymous
 * principals as equal, so it's no gate on a public agent: the principal-authed
 * read surfaces (transcript, approval detail) require an identified principal,
 * else one anonymous caller could read another anonymous session's data.
 */
function isIdentifiedPrincipal(p: SessionPrincipal): boolean {
    return p.kind !== 'anonymous'
}

/** Stable id of the decider, by principal kind — stored as the approval's `decided_by`. */
function principalDeciderId(p: SessionPrincipal): string {
    switch (p.kind) {
        case 'posthog':
            return p.user_id
        case 'jwt':
            return p.sub
        case 'slack':
            return p.agent_user_id ?? p.slack_user_id
        default:
            return 'unknown'
    }
}

/** Minimal self-contained HTML for the OAuth callback result page. */
function linkResultPage(message: string): string {
    const safe = message.replace(/[<>&]/g, (c) => ({ '<': '&lt;', '>': '&gt;', '&': '&amp;' })[c] ?? c)
    return `<!doctype html><meta charset="utf-8"><title>PostHog agent linking</title><body style="font-family:system-ui;max-width:32rem;margin:4rem auto;padding:0 1rem;color:#111"><h2>PostHog agent</h2><p style="font-size:1.05rem">${safe}</p></body>`
}

export function buildApp(opts: BuildAppOpts): Express {
    const app = express()
    // Dev only: serve /metrics on the request port (no dedicated scrape server —
    // three services on one host would collide). First in the chain so scrapes
    // bypass logging + routing. Prod uses the dedicated port and never serves
    // /metrics on this public listener.
    if (isDev()) {
        app.use((req, res, next) => {
            if (!handleMetricsRequest(req, res, log)) {
                next()
            }
        })
    }
    // First in the chain so it sees — and times — every request, including
    // those that never match a route (404s) or fail body parsing (400s).
    app.use(requestLogger(log))
    // Record HTTP latency/status for every request. Sits right after the
    // logger so it shares the same view of unmatched + rejected requests.
    app.use(httpMetricsMiddleware())
    const bus = opts.bus
    const resolver = new RevisionResolver({
        revisions: opts.revisions,
        mode: opts.routingMode,
        domainSuffix: opts.domainSuffix,
        pathPrefix: opts.pathPrefix,
        internalSigningKey: opts.internalSigningKey,
    })
    app.use(
        express.json({
            verify: (req: Request, _res, buf) => {
                ;(req as Request & { rawBody?: string }).rawBody = buf.toString('utf-8')
            },
        })
    )
    // Slack interactivity posts `application/x-www-form-urlencoded` with a
    // `payload=<json>` field. The raw body is captured the same way so
    // signature verification can hash it.
    app.use(
        express.urlencoded({
            extended: false,
            verify: (req: Request, _res, buf) => {
                ;(req as Request & { rawBody?: string }).rawBody = buf.toString('utf-8')
            },
        })
    )
    app.get('/healthz', (_req, res) => {
        res.json({ ok: true })
    })

    // OAuth identity-linking callback. The provider's `initiate` (run inside a
    // tool's `ctx.identity.resolve`) pointed the IdP redirect here. We peek the
    // single-use state to find the app, rebuild the provider from its spec +
    // decrypted env, then `complete` (which consumes the state, exchanges the
    // code, and persists the linked credential). Root-level — not under
    // /agents/:slug — so the redirect URI is stable across routing modes.
    app.get(
        '/link/:provider/callback',
        asyncHandler(async (req: Request, res: Response) => {
            const { identityLinks, identityCredentials, envEncryption, http } = opts
            if (!identityLinks || !identityCredentials || !envEncryption || !http) {
                res.status(500).send(linkResultPage('Identity linking is not configured on this ingress.'))
                return
            }
            const providerId = req.params.provider
            const stateId = typeof req.query.state === 'string' ? req.query.state : ''
            const code = typeof req.query.code === 'string' ? req.query.code : undefined
            const errorParam = typeof req.query.error === 'string' ? req.query.error : undefined
            if (errorParam) {
                res.status(400).send(linkResultPage(`Authorization was denied (${errorParam}).`))
                return
            }
            const peeked = await identityLinks.peek(stateId)
            if (!peeked || peeked.provider !== providerId) {
                res.status(400).send(
                    linkResultPage('This link has expired or was already used — ask the agent for a fresh one.')
                )
                return
            }
            const application = await opts.revisions.getApplication(peeked.applicationId)
            const revision = application?.live_revision_id
                ? await opts.revisions.getRevision(application.live_revision_id)
                : null
            if (!revision) {
                res.status(404).send(linkResultPage('The agent for this link is no longer available.'))
                return
            }
            const env = envEncryption.decryptJsonEnv(revision.encrypted_env)
            const registry = buildIdentityRegistry(revision.spec.identity_providers, {
                links: identityLinks,
                credentials: identityCredentials,
                http,
                secret: (name) => env[name],
                posthogBaseUrl: opts.posthogApiBaseUrl,
            })
            const provider = registry.get(providerId)
            if (!provider) {
                res.status(400).send(linkResultPage(`Unknown provider "${providerId}".`))
                return
            }
            try {
                await provider.complete({ stateId, query: { code, error: errorParam } })
            } catch (err) {
                log.warn(
                    { provider: providerId, err: err instanceof Error ? err.message : String(err) },
                    'identity_link_callback_failed'
                )
                res.status(400).send(linkResultPage('Linking failed — please try again from the chat.'))
                return
            }
            res.status(200).send(
                linkResultPage(`Connected ${providerId}. You can close this tab and return to your chat.`)
            )
        })
    )

    const authProvider = opts.authProvider ?? PUBLIC_ONLY_AUTH_PROVIDER
    // Superset of every trigger's deps — each module's router picks what it
    // needs. Slack uses `signingSecretResolver`+`identities`; chat/webhook/mcp
    // ignore them. Centralising the assembly here keeps the registry uniform.
    const triggerDeps = {
        resolver,
        queue: opts.queue,
        bus,
        authProvider,
        signingSecretResolver: opts.slackSigningSecretResolver ?? UNCONFIGURED_SLACK_SIGNING_SECRET_RESOLVER,
        identities: opts.identities,
        approvals: opts.approvals,
        broker: opts.credentialBroker,
        http: opts.http,
        routingMode: opts.routingMode,
        domainSuffix: opts.domainSuffix,
        publicBaseUrl: opts.publicBaseUrl,
    } as const
    const mount = opts.routingMode === 'path' ? `${opts.pathPrefix ?? '/agents'}/:slug` : ''

    // Principal tool-approval decisions — the lightweight, identity-matched
    // counterpart to the Slack interactivity handler, for posthog (PostHog Code)
    // and jwt principals. Authenticated by the same verifier the agent's
    // chat/mcp trigger uses, then required to BE the session principal — a
    // generic identity match, NOT a PostHog-authority check. `agent`-type
    // approvals are rejected here; team admins decide those in the console.
    const ApprovalDecideBodySchema = z.object({
        decision: z.enum(['approve', 'reject']),
        reason: z.string().optional(),
        edited_args: z.record(z.string(), z.unknown()).optional(),
    })
    // Mount-relative (like the trigger routes) so a client appends it to the
    // same per-agent ingress base it uses for `/send` (PostHog Code does). The
    // `:slug` is unused — the row is resolved from the approval id, not the
    // slug — but keeping the path under the mount matches how clients address
    // the ingress. In domain mode `mount` is '' so it's `/approvals/:id/decide`.
    app.post(
        `${mount}/approvals/:id/decide`,
        asyncHandler(async (req: Request, res: Response) => {
            if (!opts.approvals) {
                res.status(500).json({ error: 'approvals_not_configured' })
                return
            }
            const parsed = ApprovalDecideBodySchema.safeParse(req.body)
            if (!parsed.success) {
                res.status(400).json({ error: 'invalid_body', issues: parsed.error.issues })
                return
            }
            const row = await opts.approvals.get(req.params.id)
            // `agent`-type rows are decided in the console — collapse to not-found
            // here so this surface never leaks or decides an owner-gated request.
            // `effectiveApprovalType` also maps legacy `team_admins` rows (which
            // have no `type`), so an in-flight pre-rebuild row can't be decided as
            // a principal request here during the migration window.
            if (!row || effectiveApprovalType(row.approver_scope) === 'agent') {
                res.status(404).json({ error: 'not_found' })
                return
            }
            const application = await opts.revisions.getApplication(row.application_id)
            const revision = application ? await opts.revisions.getRevision(row.revision_id) : null
            const session = await opts.queue.getForApplication(row.session_id, row.application_id)
            if (!application || !revision || !session) {
                res.status(404).json({ error: 'not_found' })
                return
            }
            const caller = await authenticatePrincipalDecider(req, application, revision, authProvider)
            if (!caller) {
                res.status(401).json({ error: 'unauthenticated' })
                return
            }
            // Principal-match: only the person who drove this session may clear
            // their own gated call.
            if (!principalsMatch(session.principal, caller)) {
                res.status(403).json({ error: 'not_session_principal' })
                return
            }
            const result = await applyApprovalDecision(
                { approvals: opts.approvals, queue: opts.queue },
                {
                    requestId: row.id,
                    applicationId: row.application_id,
                    decision: parsed.data.decision,
                    decidedBy: principalDeciderId(caller),
                    reason: parsed.data.reason,
                    editedArgs: parsed.data.edited_args,
                }
            )
            if (!result.ok) {
                const status = result.error === 'not_found' ? 404 : result.error === 'edits_not_allowed' ? 422 : 409
                res.status(status).json(
                    result.state ? { error: result.error, state: result.state } : { error: result.error }
                )
                return
            }
            res.json({ ok: true, state: result.state })
        })
    )

    // Read side of the principal-decision surface — the deep-link approval modal
    // fetches one approval straight from the ingress, authenticated as the session
    // principal, so it never touches the project-scoped Django endpoint. This is
    // what makes the approval loop work from any project (the ingress is
    // slug-routed, the row is resolved under the route's resolved application).
    // The inline chat card doesn't use this — it's fed by `approval_required` /
    // `approval_resolved` frames on `/listen` (push, no poll). Only
    // principal-decidable rows are returned — `agent`-scope stays in the console.
    const respondWithApproval = async (req: Request, res: Response): Promise<void> => {
        if (!opts.approvals) {
            res.status(500).json({ error: 'approvals_not_configured' })
            return
        }
        const resolved = await resolveAgent(resolver, req, res)
        if (!resolved) {
            return
        }
        // Tenant-scope the lookup to the resolved application so a leaked id can't
        // resolve another agent's request; `agent`-scope collapses to not-found,
        // exactly as the decide route does.
        const row = await opts.approvals.getForApplication(req.params.id, resolved.application.id)
        if (!row || effectiveApprovalType(row.approver_scope) === 'agent') {
            res.status(404).json({ error: 'not_found' })
            return
        }
        const session = await opts.queue.getForApplication(row.session_id, resolved.application.id)
        if (!session) {
            res.status(404).json({ error: 'not_found' })
            return
        }
        const caller = await authenticatePrincipalDecider(req, resolved.application, resolved.revision, authProvider)
        if (!caller) {
            res.status(401).json({ error: 'unauthenticated' })
            return
        }
        if (!isIdentifiedPrincipal(caller)) {
            res.status(403).json({ error: 'forbidden' })
            return
        }
        if (!principalsMatch(session.principal, caller)) {
            res.status(403).json({ error: 'not_session_principal' })
            return
        }
        res.json(serializeApprovalRequest(row))
    }
    app.get(`${mount}/approvals/:id`, asyncHandler(respondWithApproval))

    // Transcript reload, principal-authed: "prove you own the session" lets a
    // client rehydrate a session's conversation from any project (the dock on
    // reopen, a web chat-list opening a past session, repainting a pending
    // approval card after a reconnect). Mirrors the janitor session-detail shape
    // (`AgentApplicationSessionDetail`) so the same client mapper consumes it,
    // including the optional `?last_n=` tail. Read-only — does not attach to or
    // resume the live `/listen` stream; that stays a separate concern.
    const respondWithSession = async (req: Request, res: Response): Promise<void> => {
        const resolved = await resolveAgent(resolver, req, res)
        if (!resolved) {
            return
        }
        const session = await opts.queue.getForApplication(req.params.id, resolved.application.id)
        if (!session) {
            res.status(404).json({ error: 'not_found' })
            return
        }
        const caller = await authenticatePrincipalDecider(req, resolved.application, resolved.revision, authProvider)
        if (!caller) {
            res.status(401).json({ error: 'unauthenticated' })
            return
        }
        if (!isIdentifiedPrincipal(caller)) {
            res.status(403).json({ error: 'forbidden' })
            return
        }
        if (!principalsMatch(session.principal, caller)) {
            res.status(403).json({ error: 'not_session_principal' })
            return
        }
        const lastNRaw = typeof req.query.last_n === 'string' ? Number.parseInt(req.query.last_n, 10) : undefined
        // `> 0`, not `>= 0`: `slice(-0)` is `slice(0)` (the whole array), so a
        // `last_n=0` must fall through to the no-trim branch, not "return zero".
        const lastN = lastNRaw !== undefined && Number.isFinite(lastNRaw) && lastNRaw > 0 ? lastNRaw : undefined
        if (lastN !== undefined && lastN < session.conversation.length) {
            res.json({
                ...session,
                conversation: session.conversation.slice(-lastN),
                conversation_total_turns: session.conversation.length,
                conversation_trimmed: true,
            })
            return
        }
        res.json({ ...session, conversation_trimmed: false })
    }
    app.get(`${mount}/sessions/:id`, asyncHandler(respondWithSession))

    // Self-describing schemas. The response cascades from `spec.triggers` ∩
    // `TRIGGER_MODULES`: only modules whose type is configured on this agent
    // appear, and each route is rendered with its auth concretely resolved
    // against the agent's `spec.auth`. There is no hand-maintained map of
    // "which triggers have schemas" — it falls out of the module registry.
    app.get(
        `${mount}/schemas`,
        asyncHandler(async (req: Request, res: Response) => {
            const resolved = await resolveAgent(resolver, req, res)
            if (!resolved) {
                if (!res.headersSent) {
                    res.status(404).json({ error: 'no_agent' })
                }
                return
            }
            const configured = new Set(resolved.revision.spec.triggers.map((t) => t.type))
            const triggers = TRIGGER_MODULES.filter((m) => configured.has(m.type)).map((m) => {
                const specTrigger = resolved.revision.spec.triggers.find((t) => t.type === m.type)
                const triggerAuth = specTrigger ? triggerAuthConfig(specTrigger) : null
                return {
                    type: m.type,
                    routes: m.routes.map((r) => {
                        // A route's `schema` (zod) drives both runtime parsing and the
                        // published shape — body for POST, query for GET. Bespoke-parse
                        // triggers (MCP, Slack) publish via the raw `bodySchema`/`querySchema`.
                        const schemaJson = r.schema ? z.toJSONSchema(r.schema) : undefined
                        const bodySchema = r.method === 'POST' ? (schemaJson ?? r.bodySchema) : r.bodySchema
                        const querySchema = r.method === 'GET' ? (schemaJson ?? r.querySchema) : r.querySchema
                        return {
                            method: r.method,
                            path: r.path,
                            ...(bodySchema ? { bodySchema } : {}),
                            ...(querySchema ? { querySchema } : {}),
                            auth: resolveRouteAuth(r.auth, triggerAuth),
                        }
                    }),
                }
            })
            res.json({
                agent: { slug: resolved.application.slug, name: resolved.application.name },
                triggers,
            })
        })
    )

    for (const m of TRIGGER_MODULES) {
        app.use(mount, mountTrigger(triggerDeps, m))
    }

    // Last in the chain. Catches rejections from `asyncHandler`-wrapped
    // routes, translates ZodError / malformed JSON / AmbiguousRevisionError
    // into structured 400s, everything else into a JSON 500.
    app.use(errorHandler(log))
    return app
}
