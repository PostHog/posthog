/**
 * Boot the ingress as a single Express app. The route table is one block —
 * triggers are siblings under the same /agents/<slug> prefix in path mode, or
 * mounted at root in domain mode.
 */

import express, { Express, Request, Response } from 'express'
import { z } from 'zod'

import type {
    EncryptedFields,
    IdentityCredentialStore,
    IdentityLinkStateStore,
    IdentityStore,
    SecretResolver,
} from '@posthog/agent-shared'
import {
    buildIdentityRegistry,
    createLogger,
    handleMetricsRequest,
    isDev,
    RevisionStore,
    SessionQueue,
    triggerAuthConfig,
} from '@posthog/agent-shared'

const log = createLogger('ingress')

import { SessionEventBus } from '@posthog/agent-shared'
import type { AuthConfig } from '@posthog/agent-shared'

import { AuthProvider, PUBLIC_ONLY_AUTH_PROVIDER } from '../enqueue/auth'
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
        broker: opts.credentialBroker,
        http: opts.http,
        routingMode: opts.routingMode,
        domainSuffix: opts.domainSuffix,
        publicBaseUrl: opts.publicBaseUrl,
    } as const
    const mount = opts.routingMode === 'path' ? `${opts.pathPrefix ?? '/agents'}/:slug` : ''

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
