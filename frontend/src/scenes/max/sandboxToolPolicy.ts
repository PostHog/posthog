import type { PermissionRequestRecord } from './types/sandboxStreamTypes'

/**
 * Default sandbox tool-permission policy, ported from Twig
 * (`packages/agent/src/adapters/claude/permissions/posthog-exec-gate.ts`).
 *
 * The deployed agent-server runs in `default` mode and asks for approval on every PostHog `exec`
 * call. We mirror Twig's policy on the client instead: auto-approve every built-in (default) tool
 * and every PostHog `exec` operation EXCEPT the destructive ones (update/delete/destroy/
 * partial-update), which still surface the approval card. Non-PostHog MCP tools fall outside the
 * default-allow contract and also prompt.
 */

/** Matches the PostHog single-exec MCP tool (`mcp__posthog__exec`, plus plugin/regional variants). */
const POSTHOG_EXEC_TOOL_RE = /^mcp__posthog(?:_[^_]+)*__exec$/
/** A sub-tool is destructive when one of these verbs appears as a whole `-`-bounded segment. */
const POSTHOG_DESTRUCTIVE_SUBTOOL_RE = /(^|-)(partial-update|update|delete|destroy)(-|$)/i

export function isPostHogExecTool(toolName: string): boolean {
    return POSTHOG_EXEC_TOOL_RE.test(toolName)
}

export function isPostHogDestructiveSubTool(subTool: string): boolean {
    return POSTHOG_DESTRUCTIVE_SUBTOOL_RE.test(subTool)
}

export type PermissionDecision = 'auto_allow' | 'prompt'

/**
 * Decide whether a permission request can be auto-approved or must prompt the user. PostHog `exec`
 * is detected by canonical tool name and by the parsed verb/sub-tool (robust to a missing
 * `_meta.claudeCode.toolName`): discovery verbs (`tools`/`search`/`info`/`schema`) and non-mutating
 * `call <sub-tool>`s auto-approve; mutating sub-tools prompt. Everything non-MCP is a built-in tool
 * and auto-approves; other MCP servers prompt.
 */
export function defaultPermissionDecision(record: PermissionRequestRecord): PermissionDecision {
    const { toolName } = record
    const { resolvedKey, innerToolName } = record.rawToolCall

    const isExec = isPostHogExecTool(toolName) || innerToolName != null || resolvedKey.startsWith('__posthog_exec_')
    if (isExec) {
        // `innerToolName` is the `call <sub-tool>` name; discovery verbs leave it unset (always safe).
        return innerToolName && isPostHogDestructiveSubTool(innerToolName) ? 'prompt' : 'auto_allow'
    }

    if (toolName.startsWith('mcp__')) {
        return 'prompt'
    }

    return 'auto_allow'
}

/** The optionId to auto-send when allowing — prefers the one-shot allow over `allow_always`. */
export function findAllowOptionId(record: PermissionRequestRecord): string | null {
    const allowOnce = record.options.find((o) => o.kind === 'allow_once')
    if (allowOnce) {
        return allowOnce.optionId
    }
    const anyAllow = record.options.find((o) => o.kind.startsWith('allow'))
    return anyAllow ? anyAllow.optionId : null
}
