/**
 * Decompose a model-visible MCP tool name (`<prefix>__<remoteName>`) into
 * the spec entry that declared it, so the dispatcher can read per-tool
 * approval gating off the same `tools[]` field that drives inclusion.
 *
 * Why a separate file: the driver's approval-wrap loop already has a
 * lookup for native + custom tools (`spec.tools.find(t => t.id === id)`).
 * MCP tools never appear in `spec.tools[]` — they materialise at session
 * start from `client.listTools()`. The fallback path lives here so the
 * driver stays a thin orchestrator and the lookup is independently
 * testable.
 *
 * The `tools[]` shape: bare string = inclusion only, object = inclusion +
 * approval policy; gating is `external` only.
 */

import { AgentSpec, ApprovalPolicy, DEFAULT_APPROVAL_POLICY, McpRef, ToolApprovalLevel } from '@posthog/agent-shared'

const PREFIX_SEPARATOR = '__'

/**
 * Effective approval level for a remote tool under the default+override model.
 *
 * Returns `null` when the ref has no `default_tool_approval` — i.e. it's a
 * LEGACY allowlist ref, and callers should fall back to the legacy
 * (bare-string / `requires_approval`) semantics. Otherwise the effective level
 * is the tool's `tools[].level` override ?? the connection default.
 *
 * Shared by `build-agent-tools.ts` (exposure: `deny` → not exposed) and
 * `lookupMcpToolApproval` (gating: `approve` → queue) so the two never drift.
 */
export function effectiveToolLevel(ref: McpRef, remoteName: string): ToolApprovalLevel | null {
    if (!ref.default_tool_approval) {
        return null
    }
    for (const entry of ref.tools ?? []) {
        if (typeof entry !== 'string' && entry.name === remoteName && entry.level) {
            return entry.level
        }
    }
    return ref.default_tool_approval
}

/**
 * Per-tool approval config materialised from a `tools[]` entry. Shape
 * intentionally mirrors `ToolRefSchema`'s `requires_approval` +
 * `approval_policy` so the driver's wrap path doesn't need to special-case
 * MCP tools vs. native/custom.
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
 *   - the matched entry has no `tools[]`, no matching name, or the matching
 *     entry is a bare string (inclusion only, no policy).
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
    // New model: `default_tool_approval` set → gate iff the effective level is
    // `approve` (the entry policy decides who/ttl). `allow` → no gate; `deny`
    // never reaches dispatch (build-agent-tools never exposes it).
    if (ref.default_tool_approval) {
        return effectiveToolLevel(ref, remoteName) === 'approve'
            ? { requires_approval: true, approval_policy: ref.approval_policy ?? DEFAULT_APPROVAL_POLICY }
            : null
    }
    // Legacy allowlist model.
    if (!ref.tools) {
        return null
    }
    for (const entry of ref.tools) {
        if (typeof entry === 'string') {
            // Bare-string entries carry no policy — they're inclusion only.
            // A name match here just means "this tool is exposed, no gating."
            continue
        }
        if (entry.name === remoteName) {
            return {
                requires_approval: entry.requires_approval,
                approval_policy: entry.approval_policy,
            }
        }
    }
    return null
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
