import { actions, afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { getCurrentTeamIdOrNone } from 'lib/utils/getAppContext'
import { sceneLogic } from 'scenes/sceneLogic'
import { Scene, SceneTab } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import type { sqlEditorTabsLogicType } from './sqlEditorTabsLogicType'

export interface SqlEditorTab {
    id: string
    label: string
}

const STORAGE_KEY_PREFIX = 'posthog-sql-editor-tabs-v1'

interface PersistedSqlEditorTab {
    id: string
    pathname: string
    search: string
    hash: string
    title: string
    customTitle?: string
    iconType: SceneTab['iconType']
    sceneId?: string
    sceneKey?: string
    pinned?: boolean
}

function getStorageKey(): string | null {
    const teamId = getCurrentTeamIdOrNone()
    if (teamId == null) {
        return null
    }
    return `${STORAGE_KEY_PREFIX}-${teamId}`
}

function isSqlEditorSceneTab(tab: SceneTab): boolean {
    if (tab.sceneId === Scene.SQLEditor) {
        return true
    }
    const pathnameOnly = (tab.pathname || '').split('?')[0]
    return pathnameOnly.endsWith('/sql')
}

function deriveLabel(tab: SceneTab, fallbackIndex: number): string {
    const trimmed = tab.customTitle?.trim()
    if (trimmed) {
        return trimmed
    }
    if (tab.title && tab.title !== 'Search' && tab.title !== 'Loading...') {
        return tab.title
    }
    return `Query ${fallbackIndex + 1}`
}

function sceneTabToPersisted(tab: SceneTab): PersistedSqlEditorTab {
    return {
        id: tab.id,
        pathname: tab.pathname,
        search: tab.search,
        hash: tab.hash,
        title: tab.title,
        customTitle: tab.customTitle,
        iconType: tab.iconType,
        sceneId: tab.sceneId,
        sceneKey: tab.sceneKey,
        pinned: tab.pinned,
    }
}

function readPersistedTabs(): PersistedSqlEditorTab[] {
    const key = getStorageKey()
    if (!key) {
        return []
    }
    try {
        const raw = localStorage.getItem(key)
        if (!raw) {
            return []
        }
        const parsed = JSON.parse(raw)
        if (!Array.isArray(parsed)) {
            return []
        }
        return parsed.filter(
            (entry): entry is PersistedSqlEditorTab =>
                entry && typeof entry === 'object' && typeof entry.id === 'string' && typeof entry.pathname === 'string'
        )
    } catch (e) {
        console.error('Failed to parse persisted SQL editor tabs', e)
        return []
    }
}

function writePersistedTabs(tabs: PersistedSqlEditorTab[]): void {
    const key = getStorageKey()
    if (!key) {
        return
    }
    try {
        if (tabs.length === 0) {
            localStorage.removeItem(key)
            return
        }
        localStorage.setItem(key, JSON.stringify(tabs))
    } catch (e) {
        console.error('Failed to persist SQL editor tabs', e)
    }
}

function tabUrl(tab: PersistedSqlEditorTab | SceneTab): string {
    return `${tab.pathname}${tab.search ?? ''}${tab.hash ?? ''}`
}

export const sqlEditorTabsLogic = kea<sqlEditorTabsLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'sqlEditorTabsLogic']),
    connect(() => ({
        values: [sceneLogic, ['tabs as allSceneTabs', 'activeTabId as sceneActiveTabId']],
        actions: [
            sceneLogic,
            [
                'newTab as sceneNewTab',
                'removeTab as sceneRemoveTab',
                'clickOnTab as sceneClickOnTab',
                'saveTabEdit',
                'setTabs as sceneSetTabs',
            ],
        ],
    })),
    actions({
        addTab: true,
        closeTab: (id: string) => ({ id }),
        setActiveTab: (id: string) => ({ id }),
        renameTab: (id: string, label: string) => ({ id, label }),
    }),
    selectors({
        tabs: [
            (s) => [s.allSceneTabs],
            (allSceneTabs: SceneTab[]): SqlEditorTab[] =>
                allSceneTabs
                    .filter(isSqlEditorSceneTab)
                    .map((tab, index) => ({ id: tab.id, label: deriveLabel(tab, index) })),
        ],
        activeTabId: [
            (s) => [s.sceneActiveTabId, s.tabs],
            (sceneActiveTabId: string | null, tabs: SqlEditorTab[]): string =>
                tabs.find((tab) => tab.id === sceneActiveTabId)?.id ?? tabs[0]?.id ?? '',
        ],
        activeTab: [
            (s) => [s.tabs, s.activeTabId],
            (tabs: SqlEditorTab[], activeTabId: string): SqlEditorTab | null =>
                tabs.find((tab) => tab.id === activeTabId) ?? tabs[0] ?? null,
        ],
        sqlEditorSceneTabs: [
            (s) => [s.allSceneTabs],
            (allSceneTabs: SceneTab[]): SceneTab[] => allSceneTabs.filter(isSqlEditorSceneTab),
        ],
    }),
    listeners(({ actions, values }) => ({
        addTab: () => {
            actions.sceneNewTab(urls.sqlEditor(), { skipNavigate: false, activate: true, source: 'new_tab_button' })
        },
        closeTab: ({ id }) => {
            const tab = values.allSceneTabs.find((t) => t.id === id)
            if (tab) {
                actions.sceneRemoveTab(tab, { source: 'close_button' })
            }
        },
        setActiveTab: ({ id }) => {
            const tab = values.allSceneTabs.find((t) => t.id === id)
            if (tab) {
                actions.sceneClickOnTab(tab)
            }
        },
        renameTab: ({ id, label }) => {
            const tab = values.allSceneTabs.find((t) => t.id === id)
            if (tab) {
                actions.saveTabEdit(tab, label)
            }
        },
    })),
    subscriptions(({ cache }) => ({
        // sqlEditorSceneTabs is `allSceneTabs.filter(...)` — `Array.filter` returns a new
        // reference on every upstream change, so this subscription fires for any
        // title/customTitle/url change too. No separate allSceneTabs subscription needed.
        sqlEditorSceneTabs: (tabs: SceneTab[]) => {
            if (!cache.hydrated) {
                return
            }
            writePersistedTabs(tabs.map(sceneTabToPersisted))
        },
    })),
    afterMount(({ actions, values, cache }) => {
        const persisted = readPersistedTabs()
        if (persisted.length === 0) {
            cache.hydrated = true
            return
        }
        const existingIds = new Set(values.allSceneTabs.map((t) => t.id))
        const existingUrls = new Set(values.allSceneTabs.map(tabUrl))
        const restoredById = new Map(persisted.map((t) => [t.id, t]))

        // Build full SceneTab records for missing persisted tabs and inject them via
        // `setTabs` directly. Going through `newTab` would emit a `posthog.capture('tab opened')`
        // event carrying `tab.hash` — and SQL editor hashes include the raw query text under
        // `#q=…`, which would leak query content into analytics on every page reload.
        const tabsToAdd: SceneTab[] = persisted
            .filter((tab) => !existingIds.has(tab.id) && !existingUrls.has(tabUrl(tab)))
            .map((persistedTab) => ({
                id: persistedTab.id,
                pathname: persistedTab.pathname,
                search: persistedTab.search ?? '',
                hash: persistedTab.hash ?? '',
                title: persistedTab.title ?? 'SQL query',
                customTitle: persistedTab.customTitle,
                iconType: persistedTab.iconType ?? 'sql_editor',
                sceneId: persistedTab.sceneId,
                sceneKey: persistedTab.sceneKey,
                pinned: persistedTab.pinned ?? false,
                active: false,
            }))

        // Mirror persisted customTitle onto any already-present tabs (the one that came from URL).
        const mergedExisting = values.allSceneTabs.map((tab) => {
            const persistedMatch = restoredById.get(tab.id) ?? persisted.find((p) => tabUrl(p) === tabUrl(tab))
            if (!persistedMatch?.customTitle || tab.customTitle) {
                return tab
            }
            return { ...tab, customTitle: persistedMatch.customTitle }
        })

        if (tabsToAdd.length === 0) {
            const changed = mergedExisting.some((tab, i) => tab.customTitle !== values.allSceneTabs[i]?.customTitle)
            if (changed) {
                actions.sceneSetTabs(mergedExisting)
            }
        } else {
            actions.sceneSetTabs([...mergedExisting, ...tabsToAdd])
        }

        cache.hydrated = true
    }),
])
