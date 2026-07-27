/**
 * Decompose a model-visible MCP tool name (`<prefix>__<remoteName>`) into
 * the spec entry that declared it, so the dispatcher can read per-tool
 * approval gating off the connection's `default_tool_approval` + `tools[]`
 * level overrides.
 *
 * Why a separate file: the driver's approval-wrap loop already has a
 * lookup for native + custom tools (`spec.tools.find(t => t.id === id)`).
 * MCP tools never appear in `spec.tools[]` — they materialise at session
 * start from `client.listTools()`. The fallback path lives here so the
 * driver stays a thin orchestrator and the lookup is independently
 * testable.
 */

import { AgentSpec, ApprovalPolicy, DEFAULT_APPROVAL_POLICY, McpRef, ToolApprovalLevel } from '@posthog/agent-shared'

export const PREFIX_SEPARATOR = '__'

/**
 * Synthetic proxy helper tools (`mcp-proxy.ts` exposes `<prefix>__explore_tools`,
 * `<prefix>__get_tool_schema`, `<prefix>__call_tool` for large connections).
 * Used by name here to keep the two files in sync without a cycle
 * (mcp-tool-lookup is a leaf; mcp-proxy imports these).
 */
export const PROXY_EXPLORE_TOOL = 'explore_tools'
export const PROXY_GET_SCHEMA_TOOL = 'get_tool_schema'
export const PROXY_CALL_TOOL = 'call_tool'

/** The synthetic read-only proxy helpers — catalog search + schema fetch, no
 *  side effects. `call_tool` is NOT here: it dispatches a real tool and the
 *  driver gates it dynamically on the underlying tool. */
const PROXY_READ_ONLY_HELPERS: ReadonlySet<string> = new Set([PROXY_EXPLORE_TOOL, PROXY_GET_SCHEMA_TOOL])

/** Prefixes of the connections running in proxy mode, derived from the driver's
 *  `<prefix>__call_tool` executor-map keys. A prefix is proxied iff its
 *  `call_tool` helper exists. */
export function proxiedPrefixesFromCallTools(callToolNames: Iterable<string>): Set<string> {
    const suffix = `${PREFIX_SEPARATOR}${PROXY_CALL_TOOL}`
    const set = new Set<string>()
    for (const name of callToolNames) {
        if (name.endsWith(suffix)) {
            set.add(name.slice(0, -suffix.length))
        }
    }
    return set
}

/**
 * True when `exposedName` is a synthetic read-only proxy helper
 * (`<prefix>__explore_tools` / `<prefix>__get_tool_schema`) for a connection in
 * `proxiedPrefixes` — those are ours, ungated. A REAL remote tool that merely
 * shares one of those names on a non-proxied connection returns false, so it's
 * gated by its level like any other tool (the bug this guards against: a blanket
 * name-based exemption let such a tool run inline without approval).
 */
export function isProxyReadOnlyHelper(exposedName: string, proxiedPrefixes: ReadonlySet<string>): boolean {
    const sep = exposedName.indexOf(PREFIX_SEPARATOR)
    if (sep <= 0) {
        return false
    }
    const prefix = exposedName.slice(0, sep)
    const remoteName = exposedName.slice(sep + PREFIX_SEPARATOR.length)
    return PROXY_READ_ONLY_HELPERS.has(remoteName) && proxiedPrefixes.has(prefix)
}

/**
 * Effective approval level for a remote tool: its `tools[].level` override ??
 * the connection's `default_tool_approval`.
 *
 * Shared by `build-agent-tools.ts` (exposure: `deny` → not exposed) and
 * `lookupMcpToolApproval` (gating: `approve` → queue) so the two never drift.
 */
export function effectiveToolLevel(ref: McpRef, remoteName: string): ToolApprovalLevel {
    for (const entry of ref.tools ?? []) {
        if (entry.name === remoteName) {
            return entry.level
        }
    }
    return ref.default_tool_approval
}

/**
 * Per-tool approval config for the driver's wrap path. Shape intentionally
 * mirrors `ToolRefSchema`'s `requires_approval` + `approval_policy` so the
 * driver doesn't need to special-case MCP tools vs. native/custom.
 */
export interface McpToolApprovalConfig {
    requires_approval: boolean
    approval_policy: ApprovalPolicy
}

/**
 * Look up the per-tool approval config for an MCP tool by its model-visible
 * name. Returns `null` for any of:
 *   - the name doesn't carry the `__` separator (caller is asking about a
 *     native / custom / client tool),
 *   - no `spec.mcps[]` entry matches the prefix,
 *   - the tool's effective level is not `approve` (no gate).
 *
 * Returning null is the "no MCP-side gating" signal — the driver falls
 * through to whatever the native/custom lookup said (typically: no gating).
 */
export function lookupMcpToolApproval(exposedName: string, spec: AgentSpec): McpToolApprovalConfig | null {
    const sep = exposedName.indexOf(PREFIX_SEPARATOR)
    if (sep <= 0 || sep >= exposedName.length - PREFIX_SEPARATOR.length) {
        return null
    }
    const prefix = exposedName.slice(0, sep)
    const remoteName = exposedName.slice(sep + PREFIX_SEPARATOR.length)
    const ref = findMcpRefByPrefix(spec.mcps, prefix)
    if (!ref) {
        return null
    }
    // Gate iff the effective level is `approve`. `allow` → no gate; `deny` never
    // reaches dispatch (build-agent-tools never exposes it). Who approves + ttl:
    // the tool's own `approval_policy` ?? the connection default ?? principal/24h.
    const entry = ref.tools?.find((t) => t.name === remoteName)
    const level = entry?.level ?? ref.default_tool_approval
    return level === 'approve'
        ? {
              requires_approval: true,
              approval_policy: entry?.approval_policy ?? ref.approval_policy ?? DEFAULT_APPROVAL_POLICY,
          }
        : null
}

/**
 * Resolve the `McpRef` whose runtime prefix matches. Mirrors the prefix
 * derivation in `mcp-clients.ts` (`id`) — keeping the two in sync is
 * load-bearing for the lookup to find the declaring entry.
 */
function findMcpRefByPrefix(mcps: ReadonlyArray<McpRef>, prefix: string): McpRef | null {
    for (const ref of mcps) {
        if (ref.id === prefix) {
            return ref
        }
    }
    return null
}

/**
 * Resolve the executor for an APPROVED row on resume. Native / custom /
 * inline-MCP tools are keyed by their exposed name directly. A proxy-routed row
 * is keyed by `<prefix>__<remoteName>` (the gate re-keyed onto the underlying
 * tool at call time), but its executor is the connection's `call_tool` — and the
 * row's stored args ARE the `call_tool` args (`{ tool_name, arguments }`), so
 * dispatching through it replays the original call. Without this fallback,
 * `executors.get(row.tool_name)` misses every proxy-routed row and the
 * human-approved call is dropped with a synthetic "unknown tool" error.
 */
export function resolveApprovedExecutor<T>(
    toolName: string,
    executors: ReadonlyMap<string, T>,
    proxyCallTools: ReadonlyMap<string, unknown>
): T | undefined {
    const direct = executors.get(toolName)
    if (direct !== undefined) {
        return direct
    }
    const key = proxyCallToolKey(toolName, proxyCallTools)
    return key ? executors.get(key) : undefined
}

/** The `<prefix>__call_tool` key for a proxy-routed `<prefix>__<remoteName>`
 *  name, or null when the prefix has no proxied connection. */
function proxyCallToolKey(toolName: string, proxyCallTools: ReadonlyMap<string, unknown>): string | null {
    const sep = toolName.indexOf(PREFIX_SEPARATOR)
    if (sep <= 0) {
        return null
    }
    const callToolName = `${toolName.slice(0, sep)}${PREFIX_SEPARATOR}${PROXY_CALL_TOOL}`
    return proxyCallTools.has(callToolName) ? callToolName : null
}
