import { actions, connect, kea, listeners, path, selectors } from 'kea'

import { sceneLogic } from 'scenes/sceneLogic'
import { Scene, SceneTab } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import type { sqlEditorTabsLogicType } from './sqlEditorTabsLogicType'

export interface SqlEditorTab {
    id: string
    label: string
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

export const sqlEditorTabsLogic = kea<sqlEditorTabsLogicType>([
    path(['scenes', 'data-warehouse', 'editor', 'sqlEditorTabsLogic']),
    connect(() => ({
        values: [sceneLogic, ['tabs as allSceneTabs', 'activeTabId as sceneActiveTabId']],
        actions: [
            sceneLogic,
            ['newTab as sceneNewTab', 'removeTab as sceneRemoveTab', 'clickOnTab as sceneClickOnTab', 'saveTabEdit'],
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
])
