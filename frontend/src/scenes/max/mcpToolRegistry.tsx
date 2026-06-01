import type { ComponentType } from 'react'

import { IconDashboard, IconGraph, IconRewindPlay, IconWarning, IconWrench } from '@posthog/icons'

import type { McpToolCallMessage } from './maxTypes'
import { CreateInsightAdapter } from './messages/adapters/CreateInsightAdapter'
import { ErrorTrackingAdapter } from './messages/adapters/ErrorTrackingAdapter'
import { SearchSessionRecordingsAdapter } from './messages/adapters/SearchSessionRecordingsAdapter'
import { UpsertDashboardAdapter } from './messages/adapters/UpsertDashboardAdapter'
import { FallbackMcpToolRenderer } from './messages/FallbackMcpToolRenderer'

export interface McpToolRendererProps {
    message: McpToolCallMessage
    isLastInGroup: boolean
}

export interface McpToolRegistryEntry {
    /**
     * Registry key. For single-exec PostHog tools, this is the **inner** tool name parsed from
     * `rawInput.command` (e.g. "execute-sql", "insight-create"); for `exec`'s discovery verbs,
     * the sentinel "__posthog_exec_tools__" etc.; for non-exec MCP tools and Claude built-ins,
     * the wire `toolName` directly (e.g. "TodoWrite", "WebSearch"). See 03_RICH_UI.md § 2.2.
     */
    key: string
    /** Display name / icon for fallback rendering and for the tool-call header line. */
    displayName: string
    icon: JSX.Element
    Renderer: ComponentType<McpToolRendererProps>
}

export interface McpToolRegistry {
    register: (entry: McpToolRegistryEntry) => void
    lookup: (toolName: string) => McpToolRegistryEntry | null
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

/**
 * Single module-level registry of MCP tool-name → renderer. All entries are registered at module
 * load — no dynamic registration, no hooks, no scene callbacks. Custom adapters land per-tool
 * (behind `phai-sandbox-tool-{slug}`) in follow-up PRs (UI-A / UI-B / UI-C); until then every tool
 * falls through to `FallbackMcpToolRenderer`. See docs/internal/posthog-ai-migration/03_RICH_UI.md
 * §§ 3.1–3.2.
 */
export const mcpToolRegistry: McpToolRegistry = new MapBackedRegistry()

// Custom adapters are registered here as they land. Each lives behind a `phai-sandbox-tool-{slug}`
// gate (runtime config, not here). The single-exec inner tool names come in two conventions across
// the in-flight specs/yaml — the hyphenated form (03_RICH_UI.md § 4.2) and the snake_case form
// (MCP_TOOLS.md). We register both aliases so dispatch is robust to whichever the MCP server emits.

// --- Data tools: insight (UI-A) ---
// VisualizationArtifactAnswer renderer — create / update / query / read insight.
for (const key of [
    'insight-create',
    'insight-update',
    'insight-query',
    'insight-read',
    'create_insight',
    'edit_insight',
    'read_insight',
]) {
    mcpToolRegistry.register({
        key,
        displayName: 'Insight',
        icon: <IconGraph />,
        Renderer: CreateInsightAdapter,
    })
}

// --- Data tools: dashboard (UI-A) ---
for (const key of ['dashboard-create', 'dashboard-update', 'upsert_dashboard']) {
    mcpToolRegistry.register({
        key,
        displayName: 'Dashboard',
        icon: <IconDashboard />,
        Renderer: UpsertDashboardAdapter,
    })
}

// --- Data tools: session recordings (UI-A) ---
for (const key of ['query-session-recordings-list', 'search_session_recordings', 'filter_session_recordings']) {
    mcpToolRegistry.register({
        key,
        displayName: 'Session recordings',
        icon: <IconRewindPlay />,
        Renderer: SearchSessionRecordingsAdapter,
    })
}

// --- Data tools: error tracking (UI-A) ---
for (const key of [
    'query-error-tracking-issues-list',
    'query-error-tracking-issue',
    'query-error-tracking-issue-events',
    'search_error_tracking_issues',
    'filter_error_tracking_issues',
]) {
    mcpToolRegistry.register({
        key,
        displayName: 'Error tracking',
        icon: <IconWarning />,
        Renderer: ErrorTrackingAdapter,
    })
}

/** Looks up the renderer entry for a resolved tool key, falling back to the generic card. */
export function lookupMcpToolRenderer(resolvedKey: string): McpToolRegistryEntry {
    return (
        mcpToolRegistry.lookup(resolvedKey) ?? {
            key: resolvedKey,
            displayName: resolvedKey,
            icon: <IconWrench />,
            Renderer: FallbackMcpToolRenderer,
        }
    )
}
