import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

export type ShellTabId = 'home' | 'activity' | 'diagnostics' | 'people'
export type ShellScopeId = 'sessions' | 'traces' | 'errors' | 'tools'

export interface ShellScope {
    id: ShellScopeId
    label: string
    path: string
    /** The key the `routes` table in `products/ai_observability/manifest.tsx` gives this path. */
    sceneKey: string
    docsUrl: string
}

export interface ShellTab {
    id: ShellTabId
    label: string
    description: string
    /** Where the tab link goes: the default scope's path when the tab has scopes. */
    path: string
    /** The manifest route key of `path`, or null when the tab's scopes carry the keys. */
    sceneKey: string | null
    scopes: readonly ShellScope[]
}

export interface ShellLocation {
    tab: ShellTabId | null
    scope: ShellScopeId | null
}

const DOCS_URL = 'https://posthog.com/docs/ai-observability'
const DEFAULT_DOCS_URL = `${DOCS_URL}/installation`

const SESSIONS: ShellScope = {
    id: 'sessions',
    label: 'Sessions',
    path: urls.aiObservabilitySessions(),
    sceneKey: 'aiObservabilitySessions',
    docsUrl: `${DOCS_URL}/sessions`,
}
const TRACES: ShellScope = {
    id: 'traces',
    label: 'Traces',
    path: urls.aiObservabilityTraces(),
    sceneKey: 'aiObservabilityTraces',
    docsUrl: `${DOCS_URL}/traces`,
}
const ERRORS: ShellScope = {
    id: 'errors',
    label: 'Errors',
    path: urls.aiObservabilityErrors(),
    sceneKey: 'aiObservabilityErrors',
    docsUrl: `${DOCS_URL}/errors`,
}
const TOOLS: ShellScope = {
    id: 'tools',
    label: 'Tools',
    path: urls.aiObservabilityTools(),
    sceneKey: 'aiObservabilityTools',
    docsUrl: `${DOCS_URL}/tools`,
}

// A fixed-length tuple, because each position has its own keyboard shortcut.
export const SHELL_TABS: readonly [ShellTab, ShellTab, ShellTab, ShellTab] = [
    {
        id: 'home',
        label: 'Home',
        description: 'Overview of your AI usage, costs, and performance.',
        path: urls.aiObservabilityDashboard(),
        sceneKey: 'aiObservabilityDashboard',
        scopes: [],
    },
    {
        id: 'activity',
        label: 'Activity',
        description: 'Every trace and session your AI has handled.',
        path: TRACES.path,
        sceneKey: null,
        scopes: [SESSIONS, TRACES],
    },
    {
        id: 'diagnostics',
        label: 'Diagnostics',
        description: 'Errors and tool calls across your traces.',
        path: ERRORS.path,
        sceneKey: null,
        scopes: [ERRORS, TOOLS],
    },
    {
        id: 'people',
        label: 'People',
        description: 'People using your AI features, with their usage and cost.',
        path: urls.aiObservabilityUsers(),
        sceneKey: 'aiObservabilityUsers',
        scopes: [],
    },
]

const NOWHERE: ShellLocation = { tab: null, scope: null }

const LOCATION_BY_SCENE_KEY: ReadonlyMap<string, ShellLocation> = new Map(
    SHELL_TABS.flatMap((tab): [string, ShellLocation][] => [
        ...(tab.sceneKey ? [[tab.sceneKey, { tab: tab.id, scope: null }] satisfies [string, ShellLocation]] : []),
        ...tab.scopes.map((scope): [string, ShellLocation] => [scope.sceneKey, { tab: tab.id, scope: scope.id }]),
    ])
)

export function shellLocationForSceneKey(sceneKey: string | null): ShellLocation {
    return (sceneKey !== null && LOCATION_BY_SCENE_KEY.get(sceneKey)) || NOWHERE
}

export function shellTab(id: ShellTabId | null): ShellTab | null {
    return SHELL_TABS.find((tab) => tab.id === id) ?? null
}

export function shellDocsUrl(location: ShellLocation): string {
    const scope = shellTab(location.tab)?.scopes.find((candidate) => candidate.id === location.scope)
    return scope?.docsUrl ?? DEFAULT_DOCS_URL
}

export function shellHref(path: string, linkParams: Record<string, unknown>): string {
    return combineUrl(path, linkParams).url
}
