import type { ComponentType } from 'react'

import { IconDashboard, IconGraph, IconNotebook, IconRewindPlay, IconWarning, IconWrench } from '@posthog/icons'

import type { McpToolCallMessage } from './maxTypes'
import { CreateInsightAdapter } from './messages/adapters/CreateInsightAdapter'
import { CreateNotebookWidget } from './messages/adapters/CreateNotebookWidget'
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
     * the wire `toolName` directly (e.g. "TodoWrite", "WebSearch").
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
 * load — no dynamic registration, no hooks, no scene callbacks. Custom adapters are registered
 * per tool; any tool without one falls through to `FallbackMcpToolRenderer`.
 */
export const mcpToolRegistry: McpToolRegistry = new MapBackedRegistry()

// Custom adapters are registered here as they land. The single-exec inner tool names exist in two
// conventions — hyphenated (the MCP yaml definitions) and snake_case (legacy Max tools) — so we
// register both aliases where both are real tool names.

// --- Data tools: insight ---
// VisualizationArtifactAnswer renderer — create / update / read insight.
for (const key of ['insight-create', 'insight-update', 'insight-get', 'create_insight']) {
    mcpToolRegistry.register({
        key,
        displayName: 'Insight',
        icon: <IconGraph />,
        Renderer: CreateInsightAdapter,
    })
}

// --- Data tools: dashboard ---
for (const key of ['dashboard-create', 'dashboard-update', 'upsert_dashboard']) {
    mcpToolRegistry.register({
        key,
        displayName: 'Dashboard',
        icon: <IconDashboard />,
        Renderer: UpsertDashboardAdapter,
    })
}

// --- Data tools: session recordings ---
for (const key of ['query-session-recordings-list', 'search_session_recordings', 'filter_session_recordings']) {
    mcpToolRegistry.register({
        key,
        displayName: 'Session recordings',
        icon: <IconRewindPlay />,
        Renderer: SearchSessionRecordingsAdapter,
    })
}

// --- Data tools: error tracking ---
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

// --- Data tools: notebooks ---
// The generated CRUD tools and the handwritten notebook-edit (the collab-safe content editor)
// all return the same REST notebook payload.
for (const key of ['notebooks-create', 'notebooks-partial-update', 'notebooks-retrieve', 'notebook-edit']) {
    mcpToolRegistry.register({
        key,
        displayName: 'Notebook',
        icon: <IconNotebook />,
        Renderer: CreateNotebookWidget,
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
