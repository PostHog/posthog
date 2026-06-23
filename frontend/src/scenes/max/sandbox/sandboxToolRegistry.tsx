import { type ComponentType, type LazyExoticComponent, lazy } from 'react'

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

import type { SandboxToolCallMessage } from '../maxTypes'

export interface SandboxToolRendererProps {
    message: SandboxToolCallMessage
    isLastInGroup: boolean
    /**
     * Resolved registry entry's icon — the registry's contribution to the card. Renderers use it for
     * the header icon (built-ins get their friendly icon instead of the generic wrench). Optional so
     * direct mounts default to the renderer's own fallback icon.
     */
    icon?: JSX.Element
    /** Resolved registry entry's stable display name, used as the header label when no title exists. */
    displayName?: string
    /** Turn-level signals so a still-incomplete tool reads as loading vs cancelled vs idle. */
    turnComplete?: boolean
    turnCancelled?: boolean
}

/** A renderer reachable eagerly or via a lazy chunk — both render identically in `SandboxToolCall`. */
type SandboxToolRendererComponent =
    | ComponentType<SandboxToolRendererProps>
    | LazyExoticComponent<ComponentType<SandboxToolRendererProps>>

export interface SandboxToolRegistryEntry {
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
    Renderer: SandboxToolRendererComponent
}

export interface SandboxToolRegistry {
    register: (entry: SandboxToolRegistryEntry) => void
    lookup: (toolName: string) => SandboxToolRegistryEntry | null
}

class MapBackedRegistry implements SandboxToolRegistry {
    private entries = new Map<string, SandboxToolRegistryEntry>()

    register(entry: SandboxToolRegistryEntry): void {
        this.entries.set(entry.key, entry)
    }

    lookup(toolName: string): SandboxToolRegistryEntry | null {
        return this.entries.get(toolName) ?? null
    }
}

// Renderers are code-split: the static graph below carries only icons, types, and lazy factories, so a
// sandbox conversation pulls a renderer's chunk on first use, not at thread mount. The built-in tools
// and the generic MCP card share one chunk (`builtinToolRenderers`); each heavy data-tool adapter and
// the Monaco-backed diff renderer stay in their own chunks.
const BuiltinToolRenderer = lazy(() =>
    import('./components/tool/builtinToolRenderers').then((m) => ({ default: m.BuiltinToolRenderer }))
)
const EditToolRenderer = lazy(() =>
    import('../messages/adapters/EditDiffRenderer').then((m) => ({ default: m.EditDiffRenderer }))
)
const InsightRenderer = lazy(() =>
    import('../messages/adapters/CreateInsightWidget').then((m) => ({ default: m.CreateInsightWidget }))
)
const DashboardRenderer = lazy(() =>
    import('../messages/adapters/UpsertDashboardWidget').then((m) => ({ default: m.UpsertDashboardWidget }))
)
const SessionRecordingsRenderer = lazy(() =>
    import('../messages/adapters/SearchSessionRecordingsWidget').then((m) => ({
        default: m.SearchSessionRecordingsWidget,
    }))
)
const ErrorTrackingRenderer = lazy(() =>
    import('../messages/adapters/ErrorTrackingWidget').then((m) => ({ default: m.ErrorTrackingWidget }))
)
const NotebookRenderer = lazy(() =>
    import('../messages/adapters/CreateNotebookWidget').then((m) => ({ default: m.CreateNotebookWidget }))
)
const QueryRenderer = lazy(() => import('../messages/adapters/QueryWidget').then((m) => ({ default: m.QueryWidget })))
const QuestionRenderer = lazy(() =>
    import('./SandboxQuestionRenderer').then((m) => ({ default: m.SandboxQuestionRenderer }))
)

/**
 * Single module-level registry of tool-name → renderer entry. All entries are registered at module
 * load — no dynamic registration, no hooks, no scene callbacks. Custom adapters are registered per
 * tool; any tool without one falls through to the built-in renderer's generic MCP card.
 */
export const sandboxToolRegistry: SandboxToolRegistry = new MapBackedRegistry()

// Custom adapters are registered here as they land. The single-exec inner tool names exist in two
// conventions — hyphenated (the MCP yaml definitions) and snake_case (legacy Max tools) — so we
// register both aliases where both are real tool names.

// --- Data tools: insight ---
// VisualizationWidget renderer — create / update / read insight.
for (const key of ['insight-create', 'insight-update', 'insight-get', 'create_insight']) {
    sandboxToolRegistry.register({
        key,
        displayName: 'Insight',
        icon: <IconGraph />,
        Renderer: InsightRenderer,
    })
}

// --- Data tools: dashboard ---
for (const key of ['dashboard-create', 'dashboard-update', 'upsert_dashboard']) {
    sandboxToolRegistry.register({
        key,
        displayName: 'Dashboard',
        icon: <IconDashboard />,
        Renderer: DashboardRenderer,
    })
}

// --- Data tools: session recordings ---
for (const key of ['query-session-recordings-list', 'search_session_recordings', 'filter_session_recordings']) {
    sandboxToolRegistry.register({
        key,
        displayName: 'Session recordings',
        icon: <IconRewindPlay />,
        Renderer: SessionRecordingsRenderer,
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
    sandboxToolRegistry.register({
        key,
        displayName: 'Error tracking',
        icon: <IconWarning />,
        Renderer: ErrorTrackingRenderer,
    })
}

// --- Data tools: notebooks ---
// The generated CRUD tools and the handwritten notebook-edit (the collab-safe content editor)
// all return the same REST notebook payload.
for (const key of ['notebooks-create', 'notebooks-partial-update', 'notebooks-retrieve', 'notebook-edit']) {
    sandboxToolRegistry.register({
        key,
        displayName: 'Notebook',
        icon: <IconNotebook />,
        Renderer: NotebookRenderer,
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
    sandboxToolRegistry.register({ key, displayName, icon, Renderer: QueryRenderer })
}

// --- Claude built-in tools ---
// Keyed by the stable SDK tool name (reachable via `_meta.claudeCode.toolName`). Bash/Read/Search/Web
// get a dedicated per-tool card; the rest fall through to the generic MCP card — all inside the single
// `BuiltinToolRenderer` chunk, which switches on the resolved tool name. The registry supplies the
// friendly icon + a stable `displayName` for frames whose `title` is empty. `Skill` is registered
// speculatively (not enumerated in the agent's tools.ts) — zero cost if never emitted. File-editing
// built-ins are split out below into the dedicated diff renderer.
const BUILTIN_TOOLS: { keys: string[]; displayName: string; icon: JSX.Element }[] = [
    { keys: ['Read', 'NotebookRead'], displayName: 'Read', icon: <IconEye /> },
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
]
for (const { keys, displayName, icon } of BUILTIN_TOOLS) {
    for (const key of keys) {
        sandboxToolRegistry.register({ key, displayName, icon, Renderer: BuiltinToolRenderer })
    }
}

// File-editing built-ins render an inline visual diff when the agent attaches `type: "diff"` content
// blocks; EditDiffRenderer falls back to the generic card when none are present.
for (const key of ['Edit', 'Write', 'NotebookEdit', 'MultiEdit']) {
    sandboxToolRegistry.register({ key, displayName: 'Edit', icon: <IconPencil />, Renderer: EditToolRenderer })
}

// PostHog single-exec discovery verbs. `resolveToolKey` parses `exec tools|search|info|schema` into
// these sentinel keys; PostHogExecRenderer (inside the built-in chunk) derives the friendly label and
// input preview from the command. Registered so they get a fitting icon instead of the wrench fallback.
const POSTHOG_EXEC_VERBS: { key: string; displayName: string; icon: JSX.Element }[] = [
    { key: '__posthog_exec_tools__', displayName: 'List tools', icon: <IconListCheck /> },
    { key: '__posthog_exec_search__', displayName: 'Search tools', icon: <IconSearch /> },
    { key: '__posthog_exec_info__', displayName: 'Read tool', icon: <IconDocument /> },
    { key: '__posthog_exec_schema__', displayName: 'Inspect schema', icon: <IconDocument /> },
    { key: '__posthog_exec_unknown__', displayName: 'Run command', icon: <IconWrench /> },
]
for (const { key, displayName, icon } of POSTHOG_EXEC_VERBS) {
    sandboxToolRegistry.register({ key, displayName, icon, Renderer: BuiltinToolRenderer })
}

// AskUserQuestion (the agent asking the user to pick between options) gets a bespoke renderer that
// lays the question + options out like the LangGraph question recap, rather than the generic JSON card.
sandboxToolRegistry.register({
    key: 'AskUserQuestion',
    displayName: 'Question',
    icon: <IconAI />,
    Renderer: QuestionRenderer,
})

/** Looks up the renderer entry for a resolved tool key, falling back to the generic built-in card. */
export function lookupSandboxToolRenderer(resolvedKey: string): SandboxToolRegistryEntry {
    return (
        sandboxToolRegistry.lookup(resolvedKey) ?? {
            key: resolvedKey,
            displayName: resolvedKey,
            icon: <IconWrench />,
            Renderer: BuiltinToolRenderer,
        }
    )
}
