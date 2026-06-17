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
    BundleStore,
    CredentialBroker,
    getSecretAllowedHosts,
    HttpFetcher,
    IntegrationCredentials,
    MemoryStore,
    TabularStore,
    Sandbox,
    ToolContext,
} from '@posthog/agent-shared'
import { getNativeTool, hasNativeTool, MAX_SLEEP_MINUTES } from '@posthog/agent-tools'

import type { OpenedMcp, RemoteMcpTool } from './mcp-clients'
import { buildToolNameMap } from './provider-safe-names'

/**
 * Meta control-flow tools — always exposed, intercepted as `terminate` results
 * instead of executing. Kept in sync with the meta tools the registry defines.
 * `@posthog/meta-emit-event` is deliberately absent: it runs like any native.
 */
export const ALWAYS_ON_NATIVE_TOOL_IDS = ['@posthog/meta-end-turn', '@posthog/meta-end-session']

/**
 * `@posthog/meta-sleep` is intercepted like the always-on meta tools, but it is
 * opt-in (an agent only gets it if its spec lists it) — sleeping changes session
 * semantics, so we don't force it on every agent. Promote it into
 * `ALWAYS_ON_NATIVE_TOOL_IDS` to make it universal later.
 */
export const SLEEP_TOOL_ID = '@posthog/meta-sleep'

const CONTROL_FLOW_IDS = new Set([...ALWAYS_ON_NATIVE_TOOL_IDS, SLEEP_TOOL_ID])

/** Control signal a meta tool surfaces to the driver via `AgentToolResult.details`. */
export type MetaControl =
    | { kind: 'end_turn' }
    | { kind: 'close'; summary?: string }
    | {
          /** `meta-sleep`: park the session until `wakeAt`, then resume. */
          kind: 'sleep'
          /** ISO timestamp the session should become claimable again. */
          wakeAt: string
          /** ISO timestamp the sleep began — paired with `wakeAt` to report actual-vs-requested on resume. */
          sleptAt: string
          /** Clamped requested duration, in minutes. */
          requestedMinutes: number
          reason?: string
      }

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
    integrations: Record<string, IntegrationCredentials>
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
}

export interface BuiltAgentTools {
    tools: AgentTool<TSchema, ToolResultDetails>[]
    /** providerSafeName → original tool id. Tools are registered under their
     * original ids (the loop matches calls by name); the driver's streamFn
     * sanitizes names on the wire and uses this map to translate the names a
     * strict provider echoes back to the original before the loop matches. */
    nameToId: Map<string, string>
}

export async function buildAgentTools(rev: AgentRevision, deps: AgentToolDeps): Promise<BuiltAgentTools> {
    const tools: AgentTool<TSchema, ToolResultDetails>[] = []
    const seen = new Set<string>()

    // `@posthog/load-skill` is auto-included only when the agent has skills —
    // exposing it otherwise just adds a tool that errors on use.
    const alwaysOn = [...ALWAYS_ON_NATIVE_TOOL_IDS]
    if (rev.spec.skills.length > 0) {
        alwaysOn.push('@posthog/load-skill')
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
            tools.push(makeNativeTool(t.id, deps))
            continue
        }
        if (t.kind === 'client') {
            // Always exposed when dispatcher is wired. No upfront capability
            // handshake: if the connecting client doesn't handle the id, the
            // dispatcher's await times out and the model gets an error
            // tool_result it can adapt to. Keeps the protocol simple +
            // matches the agent.md degradation rules.
            if (!deps.dispatchClientTool) {
                continue
            }
            tools.push(makeClientTool(t, deps))
            continue
        }
        // custom — schema + description from the bundle, dispatched via sandbox.
        const { description, parameters } = await loadCustomSchema(rev, t.id, t.path, deps.bundle)
        tools.push(makeCustomTool(t.id, description, parameters, deps))
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
                    // (`mcp_secret_not_resolved`, `mcp_integration_not_resolved`,
                    // `duplicate_mcp_prefix`).
                    throw new Error(`mcp_list_tools_failed:${client.prefix}: ${(err as Error).message}`)
                }
            })
        )
        for (const { client, tools: remoteTools } of listings) {
            // PR 7: inclusion filter migrated from `allowlist[]` to `tools[]`,
            // which carries both bare-string entries (passthrough — was
            // allowlist) and object entries `{ name, requires_approval?, ... }`.
            // We only need the entry NAMES here; the approval-wrap fallback
            // lives in `driver.ts` and pulls the per-tool policy via
            // `mcp-tool-lookup.ts` (added in commit B). Omitted/empty `tools`
            // still means "expose every tool the server lists."
            const includedNames =
                client.ref.tools && client.ref.tools.length > 0
                    ? new Set(client.ref.tools.map((t) => (typeof t === 'string' ? t : t.name)))
                    : null
            for (const remote of remoteTools) {
                if (includedNames && !includedNames.has(remote.name)) {
                    continue
                }
                // `<prefix>__<remoteName>` is the model-visible identifier; the
                // model sees the prefix so it can disambiguate (`linear__create_issue`
                // vs `github__create_issue`). All chars are already
                // provider-safe — `__` is in the safe set.
                const exposedName = `${client.prefix}__${remote.name}`
                if (seen.has(exposedName)) {
                    // Collisions can happen when a remote tool name accidentally
                    // matches a native/custom id, or two MCPs export the same
                    // post-prefix string. Same silent-skip behaviour as
                    // duplicate spec.tools entries — keeps the model surface
                    // stable across deploys instead of failing loudly on a
                    // remote-side rename.
                    continue
                }
                seen.add(exposedName)
                tools.push(makeMcpTool(exposedName, client, remote))
            }
        }
    }

    // Tools are named with their original ids (the loop matches calls by name).
    // The map keys the provider-safe form back to the original so the driver's
    // streamFn can translate names a strict provider echoed back.
    return { tools, nameToId: buildToolNameMap(tools.map((t) => t.name)) }
}

function makeControlFlowTool(id: string): AgentTool<TSchema, ToolResultDetails> {
    const native = getNativeTool(id)
    return {
        name: id,
        label: id,
        description: native.schema.description,
        parameters: native.schema.args,
        execute: async (_callId, args): Promise<AgentToolResult<ToolResultDetails>> => {
            if (id === SLEEP_TOOL_ID) {
                const a = args as { duration_minutes?: number; reason?: string }
                // Clamp in code: TypeBox bounds on args aren't enforced at call
                // time, so a model could ask for 0 or 10_000. Floor at 1 minute.
                const requestedMinutes = Math.min(
                    MAX_SLEEP_MINUTES,
                    Math.max(1, Math.round(typeof a.duration_minutes === 'number' ? a.duration_minutes : 1))
                )
                const now = Date.now()
                const sleptAt = new Date(now).toISOString()
                const wakeAt = new Date(now + requestedMinutes * 60_000).toISOString()
                return {
                    content: [{ type: 'text', text: JSON.stringify({ sleeping: true, wake_at: wakeAt }) }],
                    details: { control: { kind: 'sleep', wakeAt, sleptAt, requestedMinutes, reason: a.reason } },
                    terminate: true,
                }
            }
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

function makeNativeTool(id: string, deps: AgentToolDeps): AgentTool<TSchema, ToolResultDetails> {
    const native = getNativeTool(id)
    return {
        name: id,
        label: id,
        description: native.schema.description,
        parameters: native.schema.args,
        execute: async (_callId, args): Promise<AgentToolResult<ToolResultDetails>> => {
            // Throws propagate: the loop renders them as an error tool_result
            // (content = message, isError: true) — same shape as the old path.
            const result = await native.run(args, buildToolContext(deps))
            return { content: [{ type: 'text', text: JSON.stringify(result) }], details: { output: result } }
        },
    }
}

function makeCustomTool(
    id: string,
    description: string,
    parameters: TSchema,
    deps: AgentToolDeps
): AgentTool<TSchema, ToolResultDetails> {
    return {
        name: id,
        label: id,
        description,
        parameters,
        execute: async (_callId, args): Promise<AgentToolResult<ToolResultDetails>> => {
            if (!deps.sandbox) {
                throw new Error(`custom tool ${id} requires a sandbox`)
            }
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
            const result = await client.callTool(remote.name, (args ?? {}) as Record<string, unknown>)
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

/** Replicates the `ToolContext` the old `dispatchTool` built for native tools. */
function buildToolContext(deps: AgentToolDeps): ToolContext {
    const credentialBroker = deps.credentialBroker
    const sessionId = deps.session.id
    // The `@posthog/*` data tools act as the invoking PostHog user, so they
    // target the caller's team — only ever set from a genuine `posthog`
    // principal. Any other principal (internal / shared_secret / slack / cron)
    // leaves it undefined and those tools fail closed (no ambient agent-team
    // access).
    const principal = deps.session.principal
    const posthogUserTeamId = principal?.kind === 'posthog' ? principal.team_id : undefined
    return {
        teamId: deps.session.team_id,
        posthogUserTeamId,
        applicationId: deps.rev.application_id,
        sessionId,
        integrations: deps.integrations,
        secret: (name) => deps.secrets[name],
        secretAllowedHosts: (name) => getSecretAllowedHosts(deps.rev.spec, name),
        log: deps.log,
        skillIndex: deps.rev.spec.skills.map((s) => ({ id: s.id, description: s.description, path: s.path })),
        readBundleFile: async (path: string): Promise<string | null> => {
            try {
                return await deps.bundle.readText(deps.rev.id, path)
            } catch {
                return null
            }
        },
        memoryStore: deps.memoryStore,
        tabularStore: deps.tabularStore,
        credentials: credentialBroker
            ? {
                  resolve: (target) => credentialBroker.resolve(sessionId, target),
              }
            : undefined,
        http: deps.http,
        posthogApiBaseUrl: deps.posthogApiBaseUrl,
    }
}

async function loadCustomSchema(
    rev: AgentRevision,
    id: string,
    path: string,
    bundle: BundleStore
): Promise<{ description: string; parameters: TSchema }> {
    const schemaPath = `${path.replace(/\/$/, '')}/schema.json`
    try {
        const raw = await bundle.readText(rev.id, schemaPath)
        const schema = JSON.parse(raw) as { description?: string; args?: unknown }
        return {
            description: schema.description ?? `custom tool ${id}`,
            parameters: (schema.args as TSchema) ?? ({ type: 'object' } as unknown as TSchema),
        }
    } catch {
        return { description: `custom tool ${id}`, parameters: { type: 'object' } as unknown as TSchema }
    }
}
