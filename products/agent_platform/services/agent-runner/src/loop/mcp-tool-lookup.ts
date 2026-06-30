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

const PREFIX_SEPARATOR = '__'

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
