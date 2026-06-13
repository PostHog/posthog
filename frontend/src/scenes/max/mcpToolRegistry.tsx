import type { ComponentType } from 'react'

import {
    IconAI,
    IconDashboard,
    IconDocument,
    IconEye,
    IconFunnels,
    IconGlobe,
    IconGraph,
    IconLifecycle,
    IconListCheck,
    IconLlmAnalytics,
    IconMagicWand,
    IconNotebook,
    IconPencil,
    IconPerson,
    IconRetention,
    IconRewindPlay,
    IconSearch,
    IconStickiness,
    IconTerminal,
    IconTrends,
    IconUserPaths,
    IconWarning,
    IconWrench,
} from '@posthog/icons'

// IconRobot is not exported from @posthog/icons — it lives only in the legacy lib icon set.
import { IconRobot } from 'lib/lemon-ui/icons'

import type { McpToolCallMessage } from './maxTypes'
import { CreateInsightWidget } from './messages/adapters/CreateInsightWidget'
import { CreateNotebookWidget } from './messages/adapters/CreateNotebookWidget'
import { ErrorTrackingWidget } from './messages/adapters/ErrorTrackingWidget'
import { QueryWidget } from './messages/adapters/QueryWidget'
import { SearchSessionRecordingsWidget } from './messages/adapters/SearchSessionRecordingsWidget'
import { UpsertDashboardWidget } from './messages/adapters/UpsertDashboardWidget'
import { FallbackMcpToolRenderer } from './messages/FallbackMcpToolRenderer'

export interface McpToolRendererProps {
    message: McpToolCallMessage
    isLastInGroup: boolean
    /**
     * Resolved registry entry's icon — the registry's contribution to the card. Renderers that fall
     * through to `FallbackMcpToolRenderer` use it for the header icon (built-ins get their friendly
     * icon instead of the generic wrench). Optional so direct mounts default to the wrench.
     */
    icon?: JSX.Element
    /** Resolved registry entry's stable display name, used as the header label when no title exists. */
    displayName?: string
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
// VisualizationWidget renderer — create / update / read insight.
for (const key of ['insight-create', 'insight-update', 'insight-get', 'create_insight']) {
    mcpToolRegistry.register({
        key,
        displayName: 'Insight',
        icon: <IconGraph />,
        Renderer: CreateInsightWidget,
    })
}

// --- Data tools: dashboard ---
for (const key of ['dashboard-create', 'dashboard-update', 'upsert_dashboard']) {
    mcpToolRegistry.register({
        key,
        displayName: 'Dashboard',
        icon: <IconDashboard />,
        Renderer: UpsertDashboardWidget,
    })
}

// --- Data tools: session recordings ---
for (const key of ['query-session-recordings-list', 'search_session_recordings', 'filter_session_recordings']) {
    mcpToolRegistry.register({
        key,
        displayName: 'Session recordings',
        icon: <IconRewindPlay />,
        Renderer: SearchSessionRecordingsWidget,
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
        Renderer: ErrorTrackingWidget,
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

// --- Data tools: query wrappers ---
// VisualizationWidget renderer — analytics and product queries executed inline by the agent.
const QUERY_WRAPPER_TOOLS: { key: string; displayName: string; icon: JSX.Element }[] = [
    { key: 'query-trends', displayName: 'Trends query', icon: <IconTrends /> },
    { key: 'query-funnel', displayName: 'Funnel query', icon: <IconFunnels /> },
    { key: 'query-retention', displayName: 'Retention query', icon: <IconRetention /> },
    { key: 'query-stickiness', displayName: 'Stickiness query', icon: <IconStickiness /> },
    { key: 'query-paths', displayName: 'Paths query', icon: <IconUserPaths /> },
    { key: 'query-lifecycle', displayName: 'Lifecycle query', icon: <IconLifecycle /> },
    { key: 'query-llm-traces-list', displayName: 'LLM traces', icon: <IconLlmAnalytics /> },
    { key: 'query-trends-actors', displayName: 'Trends persons', icon: <IconPerson /> },
    { key: 'query-lifecycle-actors', displayName: 'Lifecycle persons', icon: <IconPerson /> },
    { key: 'query-paths-actors', displayName: 'Paths persons', icon: <IconPerson /> },
]
for (const { key, displayName, icon } of QUERY_WRAPPER_TOOLS) {
    mcpToolRegistry.register({ key, displayName, icon, Renderer: QueryWidget })
}

// --- Claude built-in tools ---
// Keyed by the stable SDK tool name (reachable via `_meta.claudeCode.toolName`). All reuse the
// fallback card — the goal is a friendly title + icon, not a bespoke widget. The fallback header
// already prefers Twig's rich `title` (e.g. "Edit `foo.ts`"), so these supply the icon and a stable
// `displayName` for any frame whose title is empty. `MultiEdit`/`Skill` are registered speculatively
// (not enumerated in Twig's tools.ts) — zero cost if never emitted.
const BUILTIN_TOOLS: { keys: string[]; displayName: string; icon: JSX.Element }[] = [
    { keys: ['Read', 'NotebookRead'], displayName: 'Read', icon: <IconEye /> },
    { keys: ['Edit', 'Write', 'NotebookEdit', 'MultiEdit'], displayName: 'Edit', icon: <IconPencil /> },
    { keys: ['Grep', 'Glob', 'LS'], displayName: 'Search', icon: <IconSearch /> },
    { keys: ['Bash', 'BashOutput', 'KillShell'], displayName: 'Terminal', icon: <IconTerminal /> },
    { keys: ['WebSearch', 'WebFetch'], displayName: 'Web', icon: <IconGlobe /> },
    { keys: ['Task', 'Agent'], displayName: 'Subagent', icon: <IconRobot /> },
    {
        keys: ['TaskCreate', 'TaskUpdate', 'TaskGet', 'TaskList', 'TodoWrite'],
        displayName: 'Tasks',
        icon: <IconListCheck />,
    },
    { keys: ['Skill'], displayName: 'Skill', icon: <IconMagicWand /> },
    { keys: ['ToolSearch'], displayName: 'Tool search', icon: <IconSearch /> },
    { keys: ['ExitPlanMode'], displayName: 'Plan', icon: <IconDocument /> },
    { keys: ['AskUserQuestion'], displayName: 'Question', icon: <IconAI /> },
]
for (const { keys, displayName, icon } of BUILTIN_TOOLS) {
    for (const key of keys) {
        mcpToolRegistry.register({ key, displayName, icon, Renderer: FallbackMcpToolRenderer })
    }
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
