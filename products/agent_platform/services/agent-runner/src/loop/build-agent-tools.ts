/**
 * Build the `AgentTool[]` for a session — the tool surface pi-agent-core's
 * loop dispatches against. Replaces the old split between `build-tool-list.ts`
 * (declarations for pi-ai) and `tool-dispatch.ts` (in-process routing): each
 * tool now carries its own `execute`, so the loop validates args against
 * `parameters` and calls `execute` directly.
 *
 * Three tool sources, mirroring the old `buildToolList` + `dispatchTool`:
 *   1. Always-on meta control-flow (`meta-end-turn`, `meta-end-session`) —
 *      surfaced as `terminate` results carrying a `control` detail the
 *      driver reads to derive the run outcome. These are intercepted
 *      before `native.run` (they never execute), exactly as
 *      `tool-dispatch.ts` did.
 *   2. Native tools (incl. `@posthog/load-skill` when the agent has skills) —
 *      `execute` builds the same `ToolContext` the old dispatcher did and calls
 *      `native.run`.
 *   3. Custom tools — `execute` routes to `sandbox.invoke`; the arg schema and
 *      description load from `<path>/schema.json` in the bundle.
 *
 * Tool-result content is kept byte-identical to the old path: a successful
 * call returns `JSON.stringify(result)` as text; a failure throws, which the
 * loop renders as an error tool_result (content = the thrown message,
 * `isError: true`) — the same shape `dispatchOne` produced. Analytics spans
 * are NOT emitted here; the driver's `tool_execution_end` sink owns that, which
 * is why each result stashes the raw return value in `details.output`.
 */

import type { AgentTool, AgentToolResult } from '@earendil-works/pi-agent-core'
import type { TSchema } from '@earendil-works/pi-ai'

import {
    AgentRevision,
    AgentSession,
    type ApprovalType,
    BundleStore,
    CredentialBroker,
    GatewayCatalog,
    getSecretAllowedHosts,
    HttpFetcher,
    IdentityAuthRequiredError,
    MemoryStore,
    TabularStore,
    Sandbox,
    ToolContext,
    WebSearchProvider,
} from '@posthog/agent-shared'
import { getNativeTool, hasNativeTool, WEB_SEARCH_TOOL_ID } from '@posthog/agent-tools'

import type { OpenedMcp, RemoteMcpTool } from './mcp-clients'
import { makeMcpProxyTools } from './mcp-proxy'
import { decideMcpExposure } from './mcp-tool-budget'
import { effectiveToolLevel } from './mcp-tool-lookup'
import { buildToolNameMap } from './provider-safe-names'

/**
 * Meta control-flow tools — always exposed, intercepted as `terminate` results
 * instead of executing. Kept in sync with the meta tools the registry defines.
 * `@posthog/meta-emit-event` is deliberately absent: it runs like any native.
 */
export const ALWAYS_ON_NATIVE_TOOL_IDS = ['@posthog/meta-end-turn', '@posthog/meta-end-session']

const CONTROL_FLOW_IDS = new Set(ALWAYS_ON_NATIVE_TOOL_IDS)

/** Control signal a meta tool surfaces to the driver via `AgentToolResult.details`. */
export type MetaControl = { kind: 'end_turn' } | { kind: 'close'; summary?: string }

/** `details` shape every tool in this adapter returns. */
export interface ToolResultDetails {
    /** Present only for meta control-flow tools — the driver maps this to a RunOutcome. */
    control?: MetaControl
    /** Raw native return value / sandbox result, for the analytics span `output`. */
    output?: unknown
    /** Set when a gated tool returned a synthetic queued-for-approval result. */
    queued?: boolean
    /** The approval request id, when `queued`. */
    requestId?: string
    /** True when the queue deduped onto an existing row (no new request). */
    deduped?: boolean
    /**
     * Approval policy on the queued row, when `queued`. Surfaced so the live
     * `tool_result` SSE event carries the same `approval` shape the persisted
     * synthetic result does — the inline card needs `allow_edit` (edit
     * affordance) and `approver_scope.type` (decidable inline vs console-only),
     * and neither is derivable from the tool_call alone.
     */
    allowEdit?: boolean
    approverType?: ApprovalType
}

/**
 * A tool's real `execute` — the un-gated path. The driver keeps a reference to
 * each tool's original execute so an approved call can be dispatched on resume
 * even after the gated tool's execute has been swapped for the queue path.
 */
export type RealToolExecute = (
    toolCallId: string,
    args: Record<string, unknown>
) => Promise<AgentToolResult<ToolResultDetails>>

/**
 * Dispatcher for `kind: "client"` tools. Resolves with the client's
 * returned `result`; rejects with `Error('client_tool_timeout')` if the
 * client doesn't post a result within `timeoutMs`, or
 * `Error('client_disconnected')` if the session is sealed mid-call.
 * The driver constructs this from the session-event bus.
 */
export type ClientToolDispatcher = (
    toolId: string,
    args: Record<string, unknown>,
    timeoutMs: number
) => Promise<unknown>

/** Per-session context the tool `execute` closures need. Supplied by the driver. */
export interface AgentToolDeps {
    rev: AgentRevision
    session: AgentSession
    sandbox: Sandbox | null
    /** Resolved plaintext secrets for native tools (custom tools get nonces via the sandbox). */
    secrets: Record<string, string>
    bundle: BundleStore
    log: (level: 'info' | 'warn' | 'error', msg: string, meta?: Record<string, unknown>) => void
    /**
     * S3-backed memory store. Forwarded into the `ToolContext` the native
     * `@posthog/memory-*` tools read from. Absent → memory tools surface
     * `memory_store_unavailable` to the model.
     */
    memoryStore?: MemoryStore
    /** Deterministic tabular store for @posthog/table-* tools. */
    tabularStore?: TabularStore
    /**
     * Web-search provider chain for `@posthog/web-search`. Forwarded onto the
     * `ToolContext`; an empty/absent chain also gates the tool out of the
     * session surface below (so the model never sees a tool that throws).
     */
    webSearchProviders?: readonly WebSearchProvider[]
    /**
     * Dispatcher for `kind: "client"` tools. The driver wires this up
     * over the session event bus: `execute` publishes a
     * `client_tool_call` event and blocks on a matching
     * `client_tool_result`. When `undefined`, client-tool refs in the
     * spec are skipped (build time falls back to no tool — model sees
     * nothing). Production-wired by the driver; the harness can leave
     * unset for tests that don't exercise client tools.
     */
    dispatchClientTool?: ClientToolDispatcher
    /** Emit `client_tool_call` for interactive tools (no in-process await). */
    emitClientToolCall?: (callId: string, toolId: string, args: Record<string, unknown>) => Promise<void>
    /**
     * Per-session credential broker, populated by ingress at /run + /send.
     * Native tools read through this for user auth materials (PostHog
     * OAuth bearer, JWT claims, etc.). Optional — when absent, any
     * `ctx.credentials.resolve()` returns null and the calling tool
     * decides how to degrade.
     */
    credentialBroker?: CredentialBroker
    /**
     * Per-asker identity resolver (spec.identity_providers). Built once per run
     * in the driver, keyed to the run's asker; forwarded to `ToolContext.identity`.
     */
    identity?: ToolContext['identity']
    /**
     * Opened MCP clients from `loop/mcp-clients.ts` — one per entry in
     * `spec.mcps[]`. `buildAgentTools` walks `client.listTools()` on each
     * and emits one `AgentTool` per remote tool, name-prefixed
     * `<prefix>__<remoteToolName>`. Lifetime is owned by the worker
     * (`acquire` at session start → `release` in the worker's `finally`).
     * Absent or empty → no MCP tools are added; the model sees only the
     * native/custom/client surface.
     */
    mcpClients?: OpenedMcp[]
    /**
     * Outbound HTTP client every native tool's `ctx.http` points at. Wired
     * once at the runner entrypoint from `HTTPS_PROXY` env (smokescreen in
     * prod, direct in dev). Required — tools assume the seam is present.
     */
    http: HttpFetcher
    /**
     * Base URL for the PostHog API the agent-applications-* tools call
     * against. Forwarded straight onto `ToolContext.posthogApiBaseUrl`.
     */
    posthogApiBaseUrl: string
    /** Gateway model catalog, forwarded onto `ToolContext.gatewayCatalog` for
     *  the `@posthog/agent-applications-models` tool. Absent when the gateway
     *  is disabled. */
    gatewayCatalog?: GatewayCatalog
}

export interface BuiltAgentTools {
    tools: AgentTool<TSchema, ToolResultDetails>[]
    /** providerSafeName → original tool id. Tools are registered under their
     * original ids (the loop matches calls by name); the driver's streamFn
     * sanitizes names on the wire and uses this map to translate the names a
     * strict provider echoes back to the original before the loop matches. */
    nameToId: Map<string, string>
    /** `<prefix>__call_tool` name → its proxy entry, per proxied connection.
     *  The driver re-keys the approval gate on the underlying tool from the
     *  args, using `resolveRemoteName` so the gate and dispatch agree on which
     *  remote name is invoked (a raw `<prefix>__<x>` tool that exists in the
     *  catalog stays raw; only an extra `<prefix>__` from the model is stripped). */
    mcpProxyCallTools: Map<string, ProxyCallToolEntry>
}

/** What the driver needs at gate time per proxied connection: the client (for
 *  `.prefix`, kept here so callers don't reach across to `mcp-clients`) plus
 *  the same resolver dispatch uses. Bundled so the two can't drift. */
export interface ProxyCallToolEntry {
    client: OpenedMcp
    resolveRemoteName: (raw: string) => string
}

export async function buildAgentTools(rev: AgentRevision, deps: AgentToolDeps): Promise<BuiltAgentTools> {
    const tools: AgentTool<TSchema, ToolResultDetails>[] = []
    const seen = new Set<string>()
    const mcpProxyCallTools = new Map<string, ProxyCallToolEntry>()

    // `@posthog/load-skill` is auto-included only when the agent has skills —
    // exposing it otherwise just adds a tool that errors on use.
    const alwaysOn = [...ALWAYS_ON_NATIVE_TOOL_IDS]
    if (rev.spec.skills.length > 0) {
        alwaysOn.push('@posthog/load-skill')
    }
    // `@posthog/identity-connect` lets the agent mint a connect/reconnect link on
    // demand — included whenever the agent has any linkable identity (declared
    // providers, or an MCP that authenticates through one), so the agent can hand
    // the user a link proactively instead of only after a tool/MCP auth failure.
    if (rev.spec.identity_providers.length > 0 || rev.spec.mcps.some((m) => m.auth?.provider)) {
        alwaysOn.push('@posthog/identity-connect')
    }
    const all = [...alwaysOn.map((id) => ({ kind: 'native' as const, id })), ...rev.spec.tools]

    for (const t of all) {
        if (seen.has(t.id)) {
            continue
        }
        seen.add(t.id)

        if (CONTROL_FLOW_IDS.has(t.id)) {
            tools.push(makeControlFlowTool(t.id))
            continue
        }
        if (t.kind === 'native') {
            // Unknown native id (stale spec): skip. It stays in `seen`, so a
            // duplicate stale entry short-circuits on the next pass.
            if (!hasNativeTool(t.id)) {
                continue
            }
            // `@posthog/web-search` is config-gated: with no provider keyed at
            // boot the chain is empty, so drop it rather than surface a tool
            // that only ever throws `web_search_not_configured`.
            if (t.id === WEB_SEARCH_TOOL_ID && !deps.webSearchProviders?.length) {
                continue
            }
            tools.push(makeNativeTool(t.id, deps))
            continue
        }
        if (t.kind === 'client') {
            // Client tools need a connected client to fulfil the call. Only
            // chat-triggered sessions have one, so for non-chat triggers we
            // hide every client tool and let the agent.md degrade — `required`
            // is only enforced when there's a client to declare support.
            // Spec freeze rejects `required:true` client tools combined with
            // non-chat triggers, so this branch is the runtime safety net.
            const chatMeta = deps.session.trigger_metadata?.kind === 'chat' ? deps.session.trigger_metadata : null
            const supported = chatMeta?.supported_client_tools ?? []
            // Dispatcher availability is a runner-side concern (server
            // misconfig); check before the caller-declaration gate so the
            // failure code points at the right party. `dispatchClientTool` is
            // always wired in prod (driver.ts:447); this branch catches the
            // case where a runner instance ships without it.
            if (!deps.dispatchClientTool) {
                if (t.required && chatMeta) {
                    throw new Error(`client_tool_dispatcher_unavailable:${t.id}`)
                }
                continue
            }
            if (!supported.includes(t.id)) {
                if (t.required && chatMeta) {
                    throw new Error(`client_tool_unsupported:${t.id}`)
                }
                continue
            }
            tools.push(makeClientTool(t, deps))
            continue
        }
        // custom — schema + description from the bundle, dispatched via sandbox.
        const { description, parameters } = await loadCustomSchema(rev, t.id, t.path, deps.bundle, deps.log)
        tools.push(makeCustomTool(t.id, description, parameters, deps, t.requires_identity))
    }

    // MCP-sourced tools — one per remote tool per opened client. `listTools()`
    // is fan-out across N MCPs; parallelise so session-start latency is bounded
    // by the slowest MCP, not the sum. Each opened client carries its own
    // `ref` (used here to filter against `allowlist` for the external variant).
    if (deps.mcpClients && deps.mcpClients.length > 0) {
        const listings = await Promise.all(
            deps.mcpClients.map(async (client) => {
                try {
                    return { client, tools: await client.listTools() }
                } catch (err) {
                    // Wrap raw SDK errors with a `mcp_list_tools_failed:<prefix>`
                    // code so the session-failure reason is attributable to a
                    // specific MCP at triage time. Matches the convention used
                    // by `mcp-clients.ts` for the other error paths
                    // (`mcp_secret_not_resolved`, `mcp_identity_unavailable`,
                    // `duplicate_mcp_prefix`).
                    throw new Error(`mcp_list_tools_failed:${client.prefix}: ${(err as Error).message}`)
                }
            })
        )
        for (const { client, tools: remoteTools } of listings) {
            const exposed = exposedRemoteTools(client, remoteTools, seen)
            // Inline below the budget; proxy a rich surface so it can't overflow the model.
            const decision = decideMcpExposure(exposed)
            if (decision.mode === 'inline') {
                for (const remote of exposed) {
                    tools.push(makeMcpTool(`${client.prefix}__${remote.name}`, client, remote))
                }
                continue
            }
            deps.log('info', 'mcp.exposure.proxy', {
                prefix: client.prefix,
                toolCount: decision.toolCount,
                serializedChars: decision.serializedChars,
                reasons: decision.reasons,
            })
            const proxy = makeMcpProxyTools(client, exposed)
            tools.push(...proxy.tools)
            mcpProxyCallTools.set(proxy.callToolName, { client, resolveRemoteName: proxy.resolveRemoteName })
        }
    }

    // Tools are named with their original ids (the loop matches calls by name).
    // The map keys the provider-safe form back to the original so the driver's
    // streamFn can translate names a strict provider echoed back.
    return { tools, nameToId: buildToolNameMap(tools.map((t) => t.name)), mcpProxyCallTools }
}

/**
 * The catalog a client should expose, shared by the inline and proxy emitters:
 * drop tools whose effective level is `deny` (connection default ?? per-tool
 * override), then `<prefix>__<name>` collision dedupe against `seen` (mutated).
 *
 * The agent's own config is the sole authority — the connection owner's
 * installation marks (`needs_approval` / `do_not_use`) are not enforced here.
 */
function exposedRemoteTools(client: OpenedMcp, remoteTools: RemoteMcpTool[], seen: Set<string>): RemoteMcpTool[] {
    const exposed: RemoteMcpTool[] = []
    for (const remote of remoteTools) {
        // Agent author's effective level: `deny` → not exposed to the model.
        if (effectiveToolLevel(client.ref, remote.name) === 'deny') {
            continue
        }
        const exposedName = `${client.prefix}__${remote.name}`
        if (seen.has(exposedName)) {
            continue
        }
        seen.add(exposedName)
        exposed.push(remote)
    }
    return exposed
}

function makeControlFlowTool(id: string): AgentTool<TSchema, ToolResultDetails> {
    const native = getNativeTool(id)
    return {
        name: id,
        label: id,
        description: native.schema.description,
        parameters: native.schema.args,
        execute: async (_callId, args): Promise<AgentToolResult<ToolResultDetails>> => {
            if (id === '@posthog/meta-end-session') {
                const summary = (args as { summary?: string }).summary
                return {
                    content: [{ type: 'text', text: JSON.stringify({ ended: true }) }],
                    details: { control: { kind: 'close', summary } },
                    terminate: true,
                }
            }
            return {
                content: [{ type: 'text', text: JSON.stringify({ ended_turn: true }) }],
                details: { control: { kind: 'end_turn' } },
                terminate: true,
            }
        },
    }
}

type IdentityGate =
    | { proceed: true; resolved?: ToolContext['resolvedIdentities'] }
    | { proceed: false; result: AgentToolResult<ToolResultDetails> }

function authRequiredResult(provider: string, authorizeUrl: string): AgentToolResult<ToolResultDetails> {
    const output = { auth_required: { provider, authorize_url: authorizeUrl } }
    return { content: [{ type: 'text', text: JSON.stringify(output) }], details: { output } }
}

/** Resolve a tool's required identity provider before it runs. Returns the
 *  resolved credential to thread into the context, or short-circuits to an
 *  auth_required result. `unknown_provider` (e.g. the `slack` bot) isn't
 *  identity-gated and proceeds. */
async function gateIdentity(
    provider: { id: string; scopes: string[] } | undefined,
    deps: AgentToolDeps
): Promise<IdentityGate> {
    if (!provider || !deps.identity) {
        return { proceed: true }
    }
    const res = await deps.identity.resolve(provider.id, provider.scopes)
    if (res.kind === 'ok') {
        return {
            proceed: true,
            resolved: { [provider.id]: { credential: res.credential, allowedHosts: res.allowedHosts } },
        }
    }
    if (res.kind === 'link_required') {
        return { proceed: false, result: authRequiredResult(res.provider, res.authorizeUrl) }
    }
    if (res.reason === 'unknown_provider') {
        return { proceed: true }
    }
    throw new Error(`identity_unavailable: ${provider.id} (${res.reason})`)
}

function makeNativeTool(id: string, deps: AgentToolDeps): AgentTool<TSchema, ToolResultDetails> {
    const native = getNativeTool(id)
    return {
        name: id,
        label: id,
        description: native.schema.description,
        parameters: native.schema.args,
        execute: async (_callId, args): Promise<AgentToolResult<ToolResultDetails>> => {
            const gate = await gateIdentity(native.schema.requires.provider, deps)
            if (!gate.proceed) {
                return gate.result
            }
            try {
                const result = await native.run(args, buildToolContext(deps, gate.resolved))
                return { content: [{ type: 'text', text: JSON.stringify(result) }], details: { output: result } }
            } catch (err) {
                if (err instanceof IdentityAuthRequiredError) {
                    return authRequiredResult(err.provider, err.authorizeUrl)
                }
                throw err
            }
        },
    }
}

function makeCustomTool(
    id: string,
    description: string,
    parameters: TSchema,
    deps: AgentToolDeps,
    requiresIdentity?: string
): AgentTool<TSchema, ToolResultDetails> {
    return {
        name: id,
        label: id,
        description,
        parameters,
        execute: async (_callId, args): Promise<AgentToolResult<ToolResultDetails>> => {
            const gate = await gateIdentity(requiresIdentity ? { id: requiresIdentity, scopes: [] } : undefined, deps)
            if (!gate.proceed) {
                return gate.result
            }
            if (!deps.sandbox) {
                throw new Error(`custom tool ${id} requires a sandbox`)
            }
            // CUSTOM-TOOL CREDENTIAL INJECTION SEAM: gate only — the resolved
            // bearer is not yet threaded into the sandbox.
            const r = await deps.sandbox.invoke({ toolId: id, action: 'default', args })
            if (!r.ok) {
                throw new Error(`${r.error.code}: ${r.error.message}`)
            }
            return { content: [{ type: 'text', text: JSON.stringify(r.result) }], details: { output: r.result } }
        },
    }
}

/**
 * Build an AgentTool for a `kind: "client"` spec entry. The execute
 * publishes a `client_tool_call` event over the session bus and waits
 * for a matching `client_tool_result` event (delivered by the ingress
 * `/sessions/<id>/client_tool_result` endpoint). If no client responds
 * within `timeout_ms`, the dispatcher rejects and the loop renders the
 * error as a tool_result for the model to adapt to.
 */
function makeClientTool(
    spec: {
        id: string
        description: string
        args_schema: Record<string, unknown>
        timeout_ms: number
        interactive: boolean
    },
    deps: AgentToolDeps
): AgentTool<TSchema, ToolResultDetails> {
    return {
        name: spec.id,
        label: spec.id,
        description: spec.description,
        parameters: spec.args_schema as unknown as TSchema,
        execute: async (callId, args): Promise<AgentToolResult<ToolResultDetails>> => {
            if (!deps.dispatchClientTool) {
                throw new Error(`client tool ${spec.id} dispatcher not wired on this driver`)
            }
            if (spec.interactive) {
                if (!deps.emitClientToolCall) {
                    throw new Error(`client tool ${spec.id} interactive emit not wired on this driver`)
                }
                await deps.emitClientToolCall(callId, spec.id, args as Record<string, unknown>)
                const queued = {
                    queued: true,
                    interactive: true,
                    call_id: callId,
                    tool_id: spec.id,
                    message: 'Awaiting user input. The result will arrive on the next turn — end this turn now.',
                }
                return { content: [{ type: 'text', text: JSON.stringify(queued) }], details: { output: queued } }
            }
            const result = await deps.dispatchClientTool(spec.id, args as Record<string, unknown>, spec.timeout_ms)
            return { content: [{ type: 'text', text: JSON.stringify(result) }], details: { output: result } }
        },
    }
}

/**
 * Adapt one remote MCP tool into an `AgentTool`. The `execute` closure routes
 * back through the open client's `callTool`; the SDK shapes thrown
 * remote-handler errors as `result.isError === true` (NOT as a rejection), so
 * we translate that back to a thrown error to match the custom-tool path —
 * the loop renders thrown errors as `isError: true` tool_result content.
 *
 * Successful results stringify the entire SDK envelope (content + structured
 * content + meta), keeping the on-the-wire shape byte-identical to the
 * native/custom/client paths. The raw envelope also lands on
 * `details.output` so the analytics span can keep the structured form.
 */
function makeMcpTool(
    exposedName: string,
    client: OpenedMcp,
    remote: RemoteMcpTool
): AgentTool<TSchema, ToolResultDetails> {
    return {
        name: exposedName,
        label: exposedName,
        description: remote.description,
        parameters: remote.inputSchema as TSchema,
        execute: async (_callId, args): Promise<AgentToolResult<ToolResultDetails>> => {
            const callArgs = (args ?? {}) as Record<string, unknown>
            const result = await client.callTool(remote.name, callArgs)
            if (result.isError) {
                // Surface the first text content as the error message — same
                // shape as `resultText()` in the driver. Keeps the model's
                // tool_result error text useful instead of a generic string.
                const firstText = (result.content as Array<{ type: string; text?: string }>).find(
                    (c) => c.type === 'text' && typeof c.text === 'string'
                )
                throw new Error(firstText?.text ?? `mcp_tool_error: ${exposedName}`)
            }
            return {
                content: [{ type: 'text', text: JSON.stringify(result) }],
                details: { output: result },
            }
        },
    }
}

function buildToolContext(deps: AgentToolDeps, resolvedIdentities?: ToolContext['resolvedIdentities']): ToolContext {
    const credentialBroker = deps.credentialBroker
    const sessionId = deps.session.id
    // The `@posthog/*` data tools act as the invoking PostHog user against an
    // explicit `project_id` the agent supplies (resolved via the `get_context`
    // client tool or `@posthog/list-projects`) — never inferred from the
    // principal — so there's no ambient team to thread onto the context here.
    return {
        teamId: deps.session.team_id,
        applicationId: deps.rev.application_id,
        sessionId,
        secret: (name) => deps.secrets[name],
        secretAllowedHosts: (name) => getSecretAllowedHosts(deps.rev.spec, name),
        log: deps.log,
        skillIndex: deps.rev.spec.skills.map((s) => ({ id: s.id, description: s.description, path: s.path })),
        readBundleFile: async (path: string): Promise<string | null> => {
            // `null` is the "file genuinely absent" signal (load-skill renders
            // it as "not found in the bundle"). An operational failure —
            // transient S3 error, auth, network blip — must NOT collapse into
            // that same null: it looks identical to a missing file, so the
            // agent reports a confident "not found" and gives up instead of
            // retrying. `exists` returns false only on a real 404 and rethrows
            // anything else, so the true cause propagates to the caller.
            if (!(await deps.bundle.exists(deps.rev.id, path))) {
                return null
            }
            return deps.bundle.readText(deps.rev.id, path)
        },
        memoryStore: deps.memoryStore,
        tabularStore: deps.tabularStore,
        webSearchProviders: deps.webSearchProviders,
        credentials: credentialBroker
            ? {
                  resolve: (target) => credentialBroker.resolve(sessionId, target),
              }
            : undefined,
        identity: deps.identity,
        resolvedIdentities,
        http: deps.http,
        posthogApiBaseUrl: deps.posthogApiBaseUrl,
        gatewayCatalog: deps.gatewayCatalog,
    }
}

async function loadCustomSchema(
    rev: AgentRevision,
    id: string,
    path: string,
    bundle: BundleStore,
    log: AgentToolDeps['log']
): Promise<{ description: string; parameters: TSchema }> {
    const schemaPath = `${path.replace(/\/$/, '')}/schema.json`
    try {
        const raw = await bundle.readText(rev.id, schemaPath)
        const schema = JSON.parse(raw) as { description?: string; args_schema?: unknown }
        const parameters = schema.args_schema as TSchema | undefined
        if (parameters == null) {
            log('warn', 'custom_tool.schema_missing_args_schema', { id, schemaPath })
        }
        return {
            description: schema.description ?? `custom tool ${id}`,
            parameters: parameters ?? ({ type: 'object' } as unknown as TSchema),
        }
    } catch (err) {
        log('warn', 'custom_tool.schema_unreadable', { id, schemaPath, err: (err as Error).message })
        return { description: `custom tool ${id}`, parameters: { type: 'object' } as unknown as TSchema }
    }
}
