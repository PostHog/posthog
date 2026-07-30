/**
 * Per-agent MCP transport. Each deployed agent exposes its own streamable
 * MCP endpoint at /agents/<slug>/mcp.
 *
 * Implementation: simple HTTP-streamable variant. The client POSTs JSON-RPC
 * messages to `/mcp`; the server replies inline plus streams session events
 * back via SSE on `/mcp/stream?session_id=...`.
 *
 * Tool surface (v0 universal default):
 *   - `ask({ message, session_id? })` — start a new session OR continue an
 *     existing one when `session_id` is supplied. Returns `{ session_id,
 *     state }` one-shot; no inline blocking.
 *
 * Resources:
 *   - `agent://session/<id>` — read the full session state (conversation,
 *     usage_total, principal, …) of a session the connected client created.
 *   - `resources/list` returns recent sessions scoped to the connection.
 *
 * Auth:
 *   - `/mcp` is `custom`: the mount guard resolves the agent + authConfig but
 *     does NOT authorize, because `initialize` must work pre-auth so a client
 *     can learn how to authenticate. Every other JSON-RPC method calls
 *     `ctx.authorize()` — public stays public, pat-gated agents demand a
 *     bearer on the MCP transport too.
 *   - `/mcp/stream` is `agent_spec` + a session ACL check — the SSE stream
 *     replays the conversation, so it is gated exactly like chat `/listen`.
 *   - `/mcp/connect-info` is `public` — discovery can't itself require auth
 *     without a chicken-and-egg, and it never carries real secrets.
 *
 * Resource visibility:
 *   - For authenticated agents (`spec.auth.mode !== 'public'`), the existing
 *     principal match is the gate: `resources/list` and `resources/read`
 *     only surface sessions whose principal matches the caller's.
 *   - For public agents, we follow standard MCP "URI is the capability" —
 *     possession of a `agent://session/<uuid>` URI is sufficient to read
 *     it. The UUID has 122 bits of entropy; this matches how MCP clients
 *     normally treat resource URIs.
 *   - We additionally honour the standard streamable-HTTP `Mcp-Session-Id`
 *     header (the one real MCP clients automatically send across requests
 *     in one client session). When present, it tags fresh sessions so
 *     `resources/list` returns only the caller's sessions on public agents.
 */

import { randomUUID } from 'crypto'
import { Request } from 'express'
import { z } from 'zod'

import {
    AgentSession,
    lastAssistantTextPreview,
    SessionPrincipal,
    TRIGGER_ROUTES,
    triggerAuthConfig,
} from '@posthog/agent-shared'

import { buildElevationResponse, principalDisplay, recordElevationRequest, requireAclAccess } from '../enqueue/acl'
import { principalsMatch } from '../enqueue/auth'
import { enqueueOrResume } from '../enqueue/enqueue'
import { activeStreams } from '../metrics'
import { McpRequestBodySchema, McpStreamQuerySchema } from './mcp.schemas'
import { getOwnedSession } from './session-access'
import {
    defineRoute,
    type AuthedRouteCtx,
    type CustomAuthRouteCtx,
    type RouteCtx,
    type TriggerDeps,
    type TriggerModule,
} from './types'

interface McpRequest {
    jsonrpc: '2.0'
    id?: number | string | null
    method: string
    params?: Record<string, unknown>
}

interface McpResponse {
    jsonrpc: '2.0'
    id: number | string | null
    result?: unknown
    error?: { code: number; message: string }
}

const SESSION_URI_PREFIX = 'agent://session/'
const RECENT_SESSIONS_LIMIT = 50

/**
 * MCP error codes — JSON-RPC standard reserves -32700..-32000 for the
 * protocol layer. -32601 is "method not found"; we reuse it for "unknown
 * tool" and "unknown resource" since the model-side handling is the same.
 * Auth failures use -32001 (server-defined application error) so clients
 * can distinguish "missing token" from a protocol-level problem.
 */
const RPC_METHOD_NOT_FOUND = -32601
const RPC_INVALID_PARAMS = -32602
const RPC_UNAUTHORIZED = -32001

async function mcpHandler(ctx: CustomAuthRouteCtx): Promise<void> {
    const { req, res, deps, resolved } = ctx
    const parsed = McpRequestBodySchema.safeParse(req.body)
    if (!parsed.success) {
        res.status(400).json({ error: 'invalid_body', issues: parsed.error.issues })
        return
    }
    const body = parsed.data as McpRequest
    const id = body.id ?? null
    const reply = (result: unknown): McpResponse => ({ jsonrpc: '2.0', id, result })
    const errReply = (code: number, message: string): McpResponse => ({
        jsonrpc: '2.0',
        id,
        error: { code, message },
    })

    // Standard MCP streamable-HTTP session id (`Mcp-Session-Id` header). Real
    // MCP clients automatically attach this after the first request. We use it
    // to scope `resources/list` — clients see their own sessions, never each
    // other's. `resources/read` doesn't gate on it (URI possession is the
    // capability), so a client can always re-read a session id it already holds.
    const mcpSessionId = extractMcpSessionId(req)

    // `initialize` is the only RPC allowed before auth runs — a client needs
    // the protocol version + capabilities so it can request the appropriate
    // auth in the next call. Handle it up front and return, so every method
    // below runs after `ctx.authorize()` with a non-optional `principal`.
    if (body.method === 'initialize') {
        // Hand back an `Mcp-Session-Id` if the client hasn't minted one.
        if (!mcpSessionId) {
            res.setHeader('Mcp-Session-Id', randomUUID())
        }
        res.json(
            reply({
                protocolVersion: '2024-11-05',
                capabilities: { tools: {}, resources: {} },
                serverInfo: {
                    name: `agent:${resolved.application.slug}`,
                    version: resolved.revision.id,
                },
            })
        )
        return
    }

    const auth = await ctx.authorize()
    if (!auth.ok) {
        res.json(errReply(RPC_UNAUTHORIZED, auth.reason))
        return
    }
    const principal = auth.principal

    switch (body.method) {
        case 'tools/list': {
            // v0: one universal tool. v1 will add author-curated entries from
            // spec.mcp.tools[].
            res.json(
                reply({
                    tools: [askToolDescriptor(resolved.application.slug, resolved.application.description)],
                })
            )
            return
        }
        case 'tools/call': {
            const params = body.params as { name: string; arguments?: Record<string, unknown> } | undefined
            if (!params || params.name !== 'ask') {
                res.json(errReply(RPC_METHOD_NOT_FOUND, `unknown tool: ${params?.name ?? ''}`))
                return
            }
            const args = params.arguments ?? {}
            const message = typeof args.message === 'string' ? args.message : ''
            if (!message) {
                res.json(errReply(RPC_INVALID_PARAMS, 'message is required'))
                return
            }
            const continuationId = typeof args.session_id === 'string' ? args.session_id : null

            if (continuationId) {
                // Continuation path: append to an existing session, matching the
                // strict-principal contract chat/send already enforces.
                const existing = await getOwnedSession(ctx, continuationId)
                if (!existing) {
                    res.json(errReply(RPC_INVALID_PARAMS, 'session_not_found'))
                    return
                }
                // Terminal-state policy mirrors chat /send (session-restart
                // redesign): `failed`/`cancelled` always terminal; `closed`
                // terminal unless the MCP trigger opts into `allow_restart`;
                // `completed` is open — re-queue and let the runner drain.
                if (existing.state === 'failed' || existing.state === 'cancelled') {
                    res.json(errReply(RPC_INVALID_PARAMS, 'session_terminal'))
                    return
                }
                if (existing.state === 'closed') {
                    const mcpTrigger = resolved.revision.spec.triggers.find((t) => t.type === 'mcp')
                    const allowRestart = mcpTrigger?.type === 'mcp' ? (mcpTrigger.config.allow_restart ?? false) : false
                    if (!allowRestart) {
                        res.json(errReply(RPC_INVALID_PARAMS, 'session_terminal'))
                        return
                    }
                }
                const aclCheck = requireAclAccess(existing, principal)
                if (aclCheck.kind === 'denied') {
                    const elevationReq = await recordElevationRequest(deps.queue, existing, {
                        requester: principal,
                        requesterDisplay: principalDisplay(principal),
                        trigger: 'mcp',
                        proposedMessage: {
                            role: 'user',
                            content: message,
                            timestamp: Date.now(),
                            sender: principal,
                        },
                    })
                    res.json(errReply(RPC_UNAUTHORIZED, JSON.stringify(buildElevationResponse(existing, elevationReq))))
                    return
                }
                await deps.queue.appendPendingInput(continuationId, {
                    role: 'user',
                    content: message,
                    timestamp: Date.now(),
                    sender: principal,
                })
                await deps.queue.update(continuationId, { state: 'queued' })
                res.json(
                    reply({
                        content: [
                            { type: 'text', text: JSON.stringify({ session_id: continuationId, state: 'queued' }) },
                        ],
                    })
                )
                return
            }

            // Fresh session. Tag external_key with the MCP session id so
            // `resources/list` can later filter to "sessions this client
            // started". Clients that don't send the header still get a working
            // session — they just won't see it in resources/list (they can read
            // it by URI since they hold the returned id).
            const externalKey = mcpSessionId ? `mcp:${mcpSessionId}:${randomUUID()}` : null
            const freshOutcome = await enqueueOrResume(
                { queue: deps.queue },
                {
                    application: resolved.application,
                    revision: resolved.revision,
                    externalKey,
                    seed: { role: 'user', content: message, timestamp: Date.now(), sender: principal },
                    principal: principal,
                    trigger: 'mcp',
                    requesterDisplay: principalDisplay(principal),
                }
            )
            if (freshOutcome.kind === 'elevation_required') {
                // The mcp-session-id-based external key is unique per request,
                // so this only fires if the client deliberately reuses an
                // mcpSessionId across principals. Mirror the continuation
                // path's denial shape for consistency.
                const elevationBody = {
                    error: 'elevation_required' as const,
                    elevation_request_id: freshOutcome.elevationRequestId,
                    session_id: freshOutcome.sessionId,
                    owner_display: freshOutcome.existingPrincipalDisplay,
                }
                res.json(errReply(RPC_UNAUTHORIZED, JSON.stringify(elevationBody)))
                return
            }
            res.json(
                reply({
                    content: [
                        { type: 'text', text: JSON.stringify({ session_id: freshOutcome.sessionId, state: 'queued' }) },
                    ],
                })
            )
            return
        }
        case 'resources/list': {
            const sessions = await deps.queue.listByApplication(resolved.application.id, {
                limit: RECENT_SESSIONS_LIMIT,
            })
            const owned = sessions.filter((s) => isSessionVisibleInList(s, mcpSessionId, principal))
            res.json(
                reply({
                    resources: owned.map((s) => ({
                        uri: `${SESSION_URI_PREFIX}${s.id}`,
                        name: `Session ${s.id.slice(0, 8)} (${s.state})`,
                        description: lastAssistantTextPreview(s.conversation) ?? '(no reply yet)',
                        mimeType: 'application/json',
                    })),
                })
            )
            return
        }
        case 'resources/read': {
            const params = body.params as { uri?: string } | undefined
            const uri = params?.uri ?? ''
            if (!uri.startsWith(SESSION_URI_PREFIX)) {
                res.json(errReply(RPC_METHOD_NOT_FOUND, `unknown resource: ${uri}`))
                return
            }
            const sessionId = uri.slice(SESSION_URI_PREFIX.length)
            const session = await getOwnedSession(ctx, sessionId)
            if (!session) {
                res.json(errReply(RPC_INVALID_PARAMS, 'session_not_found'))
                return
            }
            if (!isSessionReadable(session, principal)) {
                res.json(errReply(RPC_UNAUTHORIZED, 'session_not_owned'))
                return
            }
            res.json(
                reply({
                    contents: [
                        {
                            uri,
                            mimeType: 'application/json',
                            text: JSON.stringify({
                                id: session.id,
                                state: session.state,
                                turns: session.conversation.length,
                                usage_total: session.usage_total,
                                conversation: session.conversation,
                                created_at: session.created_at,
                                updated_at: session.updated_at,
                            }),
                        },
                    ],
                })
            )
            return
        }
        default:
            res.json(errReply(RPC_METHOD_NOT_FOUND, `unknown method: ${body.method}`))
    }
}

async function mcpStreamHandler(ctx: AuthedRouteCtx<z.infer<typeof McpStreamQuerySchema>>): Promise<void> {
    const { req, res, deps } = ctx
    const { session_id: sessionId } = ctx.parsed
    // Scope the session to the resolved agent — a leaked anonymous session UUID
    // must not be subscribable via another public agent's /mcp/stream. Mismatch
    // reads as not-found.
    const existing = await getOwnedSession(ctx, sessionId)
    if (!existing) {
        res.status(404).json({ error: 'session_not_found' })
        return
    }
    // The SSE stream replays the conversation events — gate it on session
    // ownership exactly like chat /listen.
    if (requireAclAccess(existing, ctx.principal).kind === 'denied') {
        res.status(403).json({ error: 'forbidden' })
        return
    }
    res.setHeader('Content-Type', 'text/event-stream')
    res.setHeader('Cache-Control', 'no-cache')
    res.flushHeaders()
    activeStreams.labels({ transport: 'mcp' }).inc()
    const unsubscribe = deps.bus.subscribe(sessionId, (event) => {
        res.write(`event: ${event.kind}\ndata: ${JSON.stringify(event)}\n\n`)
    })
    req.on('close', () => {
        unsubscribe()
        activeStreams.labels({ transport: 'mcp' }).dec()
    })
}

async function mcpConnectInfoHandler(ctx: RouteCtx): Promise<void> {
    const { req, res, deps, resolved } = ctx
    const mcpTrigger = resolved.revision.spec.triggers.find((t) => t.type === 'mcp')
    const authConfig = mcpTrigger ? triggerAuthConfig(mcpTrigger) : null
    if (!authConfig) {
        res.status(404).json({ error: 'no_mcp_trigger' })
        return
    }
    const url = agentMcpUrl(deps, req, resolved.application.slug)
    // Multi-mode auth specs collapse to a single connect snippet — pick the
    // most specific accepted mode (non-public preferred). Clients that want
    // all accepted modes introspect via /schemas; the snippet is a one-shot
    // copy-paste affordance.
    const modes = authConfig.modes
    // Defensive fallback when modes[] is somehow empty (legacy data bypassing
    // the schema default). Use `posthog_internal` rather than `public` so an
    // unconfigured agent never renders an anonymous connect snippet.
    const primary = modes.find((m) => m.type !== 'public') ?? modes[0] ?? { type: 'posthog_internal' }
    const connectAuthInput =
        primary.type === 'shared_secret' ? { mode: 'shared_secret', header: primary.header } : { mode: primary.type }
    const auth = buildConnectAuth(connectAuthInput)
    const snippets = buildConnectSnippets(resolved.application.slug, url, auth)
    res.json({ url, transport: 'http', auth, snippets })
}

/**
 * Absolute URL of the agent's MCP endpoint, matching what the ingress actually
 * serves in each routing mode (mirrors Django's `agent_ingress_route_url`):
 *
 *   domain → `https://<slug><domainSuffix>/mcp`  (slug in host, routes at root)
 *   path   → `<publicBaseUrl>/agents/<slug>/mcp` (slug in path)
 *
 * In domain mode without a configured suffix the inbound request already
 * arrived at the agent's own host, so reconstruct from it.
 */
function agentMcpUrl(deps: TriggerDeps, req: Request, slug: string): string {
    if ((deps.routingMode ?? 'path') === 'domain') {
        const suffix = deps.domainSuffix?.trim()
        const base = suffix ? `https://${slug}${suffix}` : `${req.protocol}://${req.get('host')}`
        return `${base.replace(/\/$/, '')}/mcp`
    }
    const base = deps.publicBaseUrl ?? `${req.protocol}://${req.get('host')}`
    return `${base.replace(/\/$/, '')}/agents/${slug}/mcp`
}

interface ConnectAuth {
    mode: 'public' | 'posthog' | 'shared_secret' | 'posthog_internal' | string
    header: string | null
    scheme: string | null
    instructions: string
}

/**
 * Translate `spec.auth` into the concrete header / scheme a connecting client
 * needs to set. Mirrors the rules in `enqueue/auth.ts:authorize()` — same
 * modes, same headers — so a client following the connect-info contract
 * actually succeeds at the auth gate.
 */
function buildConnectAuth(specAuth: { mode: string; header?: string }): ConnectAuth {
    if (specAuth.mode === 'public') {
        return {
            mode: 'public',
            header: null,
            scheme: null,
            instructions: 'No authentication required — connect anonymously.',
        }
    }
    if (specAuth.mode === 'posthog') {
        return {
            mode: 'posthog',
            header: 'Authorization',
            scheme: 'Bearer',
            instructions:
                'Set Authorization: Bearer <YOUR_POSTHOG_API_KEY>. Create a personal API key at /me/settings#personal-api-keys; scope it `agents:read`.',
        }
    }
    if (specAuth.mode === 'posthog_internal') {
        return {
            mode: 'posthog_internal',
            header: 'x-posthog-internal',
            scheme: null,
            instructions:
                'Server-to-server only. Set x-posthog-internal: <INTERNAL_SECRET> using the same shared secret deployed to the ingress.',
        }
    }
    if (specAuth.mode === 'shared_secret') {
        const header = specAuth.header ?? 'x-agent-shared-secret'
        return {
            mode: 'shared_secret',
            header,
            scheme: null,
            instructions: `Set ${header}: <YOUR_SHARED_SECRET> using the secret your agent author distributed.`,
        }
    }
    return {
        mode: specAuth.mode,
        header: null,
        scheme: null,
        instructions: `Unknown auth mode \`${specAuth.mode}\` — contact the agent author.`,
    }
}

/**
 * Render the paste-ready snippets. We deliberately do NOT embed any real
 * secret in the snippet — placeholders only. The connecting client resolves
 * them from their own secret store.
 */
function buildConnectSnippets(
    slug: string,
    url: string,
    auth: ConnectAuth
): { claude_code_command: string; mcp_json: Record<string, unknown> } {
    const headers: Record<string, string> = {}
    if (auth.mode === 'posthog') {
        headers.Authorization = 'Bearer <YOUR_POSTHOG_API_KEY>'
    } else if (auth.mode === 'posthog_internal') {
        headers['x-posthog-internal'] = '<INTERNAL_SECRET>'
    } else if (auth.mode === 'shared_secret' && auth.header) {
        headers[auth.header] = '<YOUR_SHARED_SECRET>'
    }

    // Claude Code `mcp add` shell command. One --header flag per header on
    // gated agents; flag-free for public agents.
    const cmdParts: string[] = ['claude', 'mcp', 'add', '--transport', 'http', slug, url]
    for (const [name, value] of Object.entries(headers)) {
        cmdParts.push('--header', `${name}=${value}`)
    }

    return {
        claude_code_command: cmdParts.join(' '),
        mcp_json: {
            mcpServers: {
                [slug]: {
                    transport: 'http',
                    url,
                    ...(Object.keys(headers).length > 0 ? { headers } : {}),
                },
            },
        },
    }
}

function askToolDescriptor(
    slug: string,
    description: string
): {
    name: string
    description: string
    inputSchema: Record<string, unknown>
} {
    // Description blends in the agent's own description so the connecting LLM's
    // routing decision considers what this agent is FOR, not just the verb
    // name. Falls back to a generic line when the author left description empty.
    const agentBlurb = description.trim().length > 0 ? description.trim() : `the ${slug} agent`
    return {
        name: 'ask',
        description: `Send a message to ${agentBlurb}. Starts a fresh thread, or continues an existing one when session_id is provided. Returns { session_id, state } — use resources/read to follow up.`,
        inputSchema: {
            type: 'object',
            properties: {
                message: {
                    type: 'string',
                    description: 'The message to send to the agent.',
                },
                session_id: {
                    type: 'string',
                    description:
                        'Optional. UUID of a session previously returned by `ask`. Supplying it continues the thread instead of starting a new one.',
                },
            },
            required: ['message'],
        },
    }
}

/**
 * Pulls the standard MCP streamable-HTTP session id off the inbound request.
 * Real MCP clients send this automatically once `initialize` has handed one
 * back via the response header. Express normalises req.headers to lower-case
 * keys, so this lookup is intentionally lower-case.
 */
function extractMcpSessionId(req: Request): string | null {
    const raw = req.headers['mcp-session-id']
    if (typeof raw !== 'string' || !raw) {
        return null
    }
    return raw
}

/**
 * Whether a session shows up in `resources/list`. Stricter than
 * `isSessionReadable` — list is for discovery, so we never expose other
 * clients' sessions on a public agent. Keys:
 *   - The session was started by the same `Mcp-Session-Id` (matched via the
 *     `mcp:<id>:` external_key prefix the trigger writes on enqueue), OR
 *   - The caller's principal is non-anonymous and matches the session's.
 *
 * Anonymous-on-anonymous matches are deliberately NOT enough — two distinct
 * anonymous clients on a public agent shouldn't enumerate each other.
 */
function isSessionVisibleInList(
    session: AgentSession,
    mcpSessionId: string | null,
    principal: SessionPrincipal
): boolean {
    if (mcpSessionId && session.external_key && session.external_key.startsWith(`mcp:${mcpSessionId}:`)) {
        return true
    }
    if (principal.kind !== 'anonymous' && principalsMatch(session.principal, principal)) {
        return true
    }
    return false
}

/**
 * Whether a session can be read via `resources/read`. Looser than
 * `isSessionVisibleInList`: possession of the `agent://session/<uuid>` URI is
 * itself the capability on public agents (standard MCP resources pattern — the
 * URI is the secret). UUIDs carry 122 bits of entropy and can't be guessed.
 *
 * For authenticated agents the principal must still match — possession of a
 * URI isn't enough when `spec.auth.mode !== 'public'`, mirroring the
 * strict-principal rule chat/send already enforce.
 */
function isSessionReadable(session: AgentSession, principal: SessionPrincipal): boolean {
    if (principal.kind === 'anonymous') {
        return session.principal === null || session.principal.kind === 'anonymous'
    }
    return principalsMatch(session.principal, principal)
}

/** Body is JSON-RPC 2.0 per the MCP transport spec. The `bodySchema` advertises
 *  the envelope; `params` shape depends on the method and is documented in the
 *  MCP spec (modelcontextprotocol.io). */
export const mcpTrigger: TriggerModule = {
    type: 'mcp',
    routes: [
        {
            method: 'POST',
            path: TRIGGER_ROUTES.mcp.rpc,
            bodySchema: z.toJSONSchema(McpRequestBodySchema),
            auth: 'custom',
            handler: mcpHandler,
        },
        defineRoute({
            method: 'GET',
            path: TRIGGER_ROUTES.mcp.stream,
            auth: 'agent_spec',
            schema: McpStreamQuerySchema,
            handler: mcpStreamHandler,
        }),
        {
            method: 'GET',
            path: TRIGGER_ROUTES.mcp.connect_info,
            // Public — anyone who knows the URL can ask "how do I connect?".
            // Discovery cannot itself require auth without a chicken-and-egg.
            auth: 'public',
            handler: mcpConnectInfoHandler,
        },
    ],
}
