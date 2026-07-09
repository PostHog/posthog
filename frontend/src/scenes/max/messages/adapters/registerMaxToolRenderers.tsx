import { type ComponentType } from 'react'

import {
    IconDashboard,
    IconFunnels,
    IconGraph,
    IconLifecycle,
    IconLlmAnalytics,
    IconNotebook,
    IconPerson,
    IconRetention,
    IconRewindPlay,
    IconStickiness,
    IconTrends,
    IconUserPaths,
    IconWarning,
} from '@posthog/icons'

import { lazyWithRetry } from 'lib/utils/lazyWithRetry'

import {
    registerToolRenderers,
    type ToolRegistryEntry,
    type ToolRendererProps,
} from 'products/posthog_ai/frontend/api/tools'

// Product-specific tool-call renderers for the PostHog AI agent run surface. These render PostHog
// product entities (insights, dashboards, recordings, error-tracking issues, notebooks, query results)
// and therefore live in scenes/max — the shared `toolRegistry` must not import them. Importing
// this module (done once by the Max scene, see Thread.tsx) registers them into the shared registry so
// they're resolved when a sandbox conversation renders the matching tool call. Surfaces that never load
// Max (tasks, signals inbox) simply fall through to the generic MCP card for these keys.
//
// Renderers are code-split: each lazyWithRetry() pulls its chunk on first use, not at registration time.
const InsightRenderer = lazyWithRetry(() =>
    import('./CreateInsightWidget').then((m) => ({ default: m.CreateInsightWidget }))
)
const DashboardRenderer = lazyWithRetry(() =>
    import('./UpsertDashboardWidget').then((m) => ({ default: m.UpsertDashboardWidget }))
)
const SessionRecordingsRenderer = lazyWithRetry(() =>
    import('./SearchSessionRecordingsWidget').then((m) => ({ default: m.SearchSessionRecordingsWidget }))
)
const ErrorTrackingRenderer = lazyWithRetry(() =>
    import('./ErrorTrackingWidget').then((m) => ({ default: m.ErrorTrackingWidget }))
)
const NotebookRenderer = lazyWithRetry(() =>
    import('./CreateNotebookWidget').then((m) => ({ default: m.CreateNotebookWidget }))
)
const QueryRenderer = lazyWithRetry(() => import('./QueryWidget').then((m) => ({ default: m.QueryWidget })))

// The single-exec inner tool names exist in two conventions — hyphenated (the MCP yaml definitions) and
// snake_case (legacy Max tools) — so we register both aliases where both are real tool names. Each call
// fans the aliases into one entry per key and feeds them through the surface's `registerToolRenderers`
// seam (Tier 4) — Max is the first consumer of that generic per-product mechanism.
function register(
    keys: string[],
    displayName: string,
    icon: JSX.Element,
    Renderer: ComponentType<ToolRendererProps>
): void {
    registerToolRenderers(keys.map((key): ToolRegistryEntry => ({ key, displayName, icon, Renderer })))
}

// --- Data tools: insight (create / update / read) ---
register(
    ['insight-create', 'insight-update', 'insight-get', 'create_insight'],
    'Insight',
    <IconGraph />,
    InsightRenderer
)

// --- Data tools: dashboard ---
register(
    ['dashboard-create', 'dashboard-update', 'upsert_dashboard'],
    'Dashboard',
    <IconDashboard />,
    DashboardRenderer
)

// --- Data tools: session recordings ---
register(
    ['query-session-recordings-list', 'search_session_recordings', 'filter_session_recordings'],
    'Session recordings',
    <IconRewindPlay />,
    SessionRecordingsRenderer
)

// --- Data tools: error tracking ---
register(
    [
        'query-error-tracking-issues-list',
        'query-error-tracking-issue',
        'query-error-tracking-issue-events',
        'search_error_tracking_issues',
        'filter_error_tracking_issues',
    ],
    'Error tracking',
    <IconWarning />,
    ErrorTrackingRenderer
)

// --- Data tools: notebooks ---
// The generated CRUD tools and the handwritten notebook-edit (the collab-safe content editor) all
// return the same REST notebook payload.
register(
    ['notebooks-create', 'notebooks-partial-update', 'notebooks-retrieve', 'notebook-edit'],
    'Notebook',
    <IconNotebook />,
    NotebookRenderer
)

// --- Data tools: query wrappers (analytics/product queries executed inline by the agent) ---
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
registerToolRenderers(
    QUERY_WRAPPER_TOOLS.map(
        ({ key, displayName, icon }): ToolRegistryEntry => ({
            key,
            displayName,
            icon,
            Renderer: QueryRenderer,
        })
    )
)
