import { ComponentType } from 'react'

import { IconWrench } from '@posthog/icons'

import { McpToolCallMessage } from './maxTypes'
import { FallbackMcpToolRenderer } from './messages/adapters/FallbackMcpToolRenderer'

/**
 * MCP tool registry for the sandbox (cloud-agent) runtime.
 *
 * The sandbox agent surfaces tool calls as ACP frames. PostHog's MCP server runs in
 * single-exec mode: the model only ever calls one tool, `exec`, and picks the real
 * operation via a CLI-style `command` string (`call <tool> {json}`). `resolveToolKey`
 * normalizes that down to a registry key; `mcpToolRegistry.lookup(key)` returns the
 * wired renderer entry, or `null` so Thread.tsx falls back to FallbackMcpToolRenderer.
 *
 * All registration happens at module load — no hooks, no dynamic/scene registration.
 * See docs/internal/posthog-ai-migration/03_RICH_UI.md §§2,3.
 */

export interface McpToolRendererProps {
    message: McpToolCallMessage
    isLastInGroup: boolean
}

export interface McpToolRegistryEntry {
    /**
     * Registry key. For single-exec PostHog tools this is the inner tool name parsed
     * from `rawInput.command` (e.g. 'insight-create'); for `exec`'s discovery verbs the
     * sentinel '__posthog_exec_tools__' etc.; for non-exec MCP tools and Claude built-ins
     * the wire `toolName` directly (e.g. 'TodoWrite'). See resolveToolKey.
     */
    key: string
    /** Display name for the tool-call header line and fallback rendering. */
    displayName: string
    icon: JSX.Element
    Renderer: ComponentType<McpToolRendererProps>
}

export interface McpToolRegistry {
    register: (entry: McpToolRegistryEntry) => void
    lookup: (toolName: string) => McpToolRegistryEntry | null
}

/** Returned for malformed single-exec `command` strings; routes to the fallback renderer. */
export const POSTHOG_EXEC_UNKNOWN_KEY = '__posthog_exec_unknown__'

/**
 * Matches the single-exec PostHog MCP outer tool. The outer tool is named `exec`
 * (qualified `mcp__posthog__exec` / `mcp__plugin_posthog__exec` / regional variants) —
 * NOT `posthog`. Ported verbatim from the cloud-agent display logic.
 */
const POSTHOG_EXEC_TOOL_RE = /^mcp__(?:plugin_)?posthog(?:_[^_]+)*__exec$/

export interface ResolvedToolKey {
    resolvedKey: string
    innerToolName?: string
    innerInput?: Record<string, unknown>
}

/**
 * Resolve the registry key for an ACP tool call.
 *
 * - Single-exec `call <tool> {json}` -> the inner tool key (+ parsed inner input).
 * - Single-exec discovery verb (tools/search/info/schema) -> '__posthog_exec_<verb>__'.
 * - Malformed single-exec command -> POSTHOG_EXEC_UNKNOWN_KEY.
 * - Any non-exec tool -> the wire `toolName` as-is.
 */
export function resolveToolKey(serverName: string, toolName: string, input: Record<string, unknown>): ResolvedToolKey {
    const fullName = `mcp__${serverName}__${toolName}`

    // Single-exec mode: parse the verb + inner tool out of `command`.
    if (POSTHOG_EXEC_TOOL_RE.test(fullName) && typeof input.command === 'string') {
        const verbMatch = input.command.match(/^\s*(tools|search|info|schema|call)(?:\s+([\s\S]*))?\s*$/)
        if (!verbMatch) {
            return { resolvedKey: POSTHOG_EXEC_UNKNOWN_KEY }
        }

        const verb = verbMatch[1] as 'tools' | 'search' | 'info' | 'schema' | 'call'
        const rest = (verbMatch[2] ?? '').trim()

        if (verb !== 'call') {
            // Discovery verbs render as a single shared adapter card (one row).
            return { resolvedKey: `__posthog_exec_${verb}__` }
        }

        // verb === 'call' — extract inner tool name + JSON body.
        const callMatch = rest.match(/^(?:--json\s+)?([a-zA-Z0-9_-]+)\s*([\s\S]*)$/)
        if (!callMatch) {
            return { resolvedKey: POSTHOG_EXEC_UNKNOWN_KEY }
        }

        const innerToolName = callMatch[1]
        const jsonBody = (callMatch[2] ?? '').trim()
        let innerInput: Record<string, unknown> = {}
        if (jsonBody) {
            try {
                innerInput = JSON.parse(jsonBody)
            } catch {
                // Leave empty — the renderer still gets the raw command for display.
            }
        }
        return { resolvedKey: innerToolName, innerToolName, innerInput }
    }

    // Non-exec MCP tools (user-installed servers) and Claude SDK built-ins look up directly.
    return { resolvedKey: toolName }
}

class MapBackedRegistry implements McpToolRegistry {
    private entries = new Map<string, McpToolRegistryEntry>()

    register(entry: McpToolRegistryEntry): void {
        this.entries.set(entry.key, entry)
    }

    lookup(toolName: string): McpToolRegistryEntry | null {
        return this.entries.get(toolName) ?? null
    }
}

/** Single module-level registry instance. Add tool adapters here as they're wired. */
export const mcpToolRegistry = new MapBackedRegistry()

/**
 * Look up a renderer entry by resolved key. Returns `null` when nothing is wired so the
 * caller (Thread.tsx) can fall back to FallbackMcpToolRenderer.
 */
export function lookupMcpToolRenderer(resolvedKey: string): McpToolRegistryEntry | null {
    return mcpToolRegistry.lookup(resolvedKey)
}

/**
 * Convenience entry for the catch-all renderer. Not registered under any key — Thread.tsx
 * reaches for it directly when `lookupMcpToolRenderer` returns `null`.
 */
export const fallbackMcpToolEntry: McpToolRegistryEntry = {
    key: POSTHOG_EXEC_UNKNOWN_KEY,
    displayName: 'Tool call',
    icon: <IconWrench />,
    Renderer: FallbackMcpToolRenderer,
}

// Tool adapters register below at module load. Custom adapters land in follow-up PRs;
// until then every tool resolves to `null` and renders via FallbackMcpToolRenderer.
// e.g. mcpToolRegistry.register({ key: 'insight-create', displayName: 'Create insight', icon: ..., Renderer: ... })
