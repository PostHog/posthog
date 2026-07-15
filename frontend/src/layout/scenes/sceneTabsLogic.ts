import { arrayMove } from '@dnd-kit/sortable'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { combineUrl, router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { isDesktopApp } from 'lib/utils/isDesktopApp'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { NEW_INTERNAL_TAB } from 'lib/utils/newInternalTab'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneTab } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import type { sceneTabsLogicType } from './sceneTabsLogicType'

/**
 * Browser-like tabs for the PostHog desktop app (products/desktop), a rebuild of the
 * scene tabs removed from the web app in #59764. Each tab is a saved location; the app
 * itself still renders a single scene, and switching tabs navigates the router.
 * Rendered (and this logic mounted) only when `isDesktopApp()`.
 */

export type TabOpenSource = 'internal_link' | 'keyboard_shortcut' | 'new_tab_button' | 'unknown'
export type TabCloseSource = 'close_button' | 'context_menu' | 'keyboard_shortcut' | 'middle_click' | 'unknown'

/** A scene tab in the desktop tab strip. Extends the base SceneTab with strip-only state. */
export interface DesktopSceneTab extends SceneTab {
    active: boolean
    pinned?: boolean
    /** Show a small badge indicator on the tab icon */
    badge?: boolean
}

const STORAGE_KEY = 'posthog-desktop-scene-tabs'

const generateTabId = (): string => crypto?.randomUUID?.()?.split('-')?.pop() || `${Date.now()}-${Math.random()}`

const freshTab = (overrides: Partial<DesktopSceneTab> = {}): DesktopSceneTab => ({
    id: generateTabId(),
    active: true,
    pathname: urls.newTab(),
    search: '',
    hash: '',
    title: 'New tab',
    iconType: 'search',
    pinned: false,
    ...overrides,
})

const partitionTabs = (tabs: DesktopSceneTab[]): { pinned: DesktopSceneTab[]; unpinned: DesktopSceneTab[] } => {
    const pinned: DesktopSceneTab[] = []
    const unpinned: DesktopSceneTab[] = []
    for (const tab of tabs) {
        if (tab.pinned) {
            pinned.push(tab)
        } else {
            unpinned.push(tab)
        }
    }
    return { pinned, unpinned }
}

const sortTabsPinnedFirst = (tabs: DesktopSceneTab[]): DesktopSceneTab[] => {
    const { pinned, unpinned } = partitionTabs(tabs)
    return [...pinned, ...unpinned]
}

const ensureActiveTab = (tabs: DesktopSceneTab[]): DesktopSceneTab[] => {
    if (!tabs.some((tab) => tab.active) && tabs.length > 0) {
        return tabs.map((tab, index) => ({ ...tab, active: index === 0 }))
    }
    return tabs
}

const updateTabPinnedState = (tabs: DesktopSceneTab[], tabId: string, pinned: boolean): DesktopSceneTab[] => {
    const index = tabs.findIndex((tab) => tab.id === tabId)
    if (index === -1) {
        return tabs
    }
    const newTabs = [...tabs]
    newTabs[index] = { ...tabs[index], pinned }
    return ensureActiveTab(sortTabsPinnedFirst(newTabs))
}

/** Strips deep routing state so tabs serialize cleanly to localStorage. */
const tabToSnapshot = (tab: DesktopSceneTab): DesktopSceneTab => {
    const { sceneParams: _omitSceneParams, ...rest } = tab
    return { ...rest, id: tab.id || generateTabId() }
}

const persistTabs = (tabs: DesktopSceneTab[]): void => {
    try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(tabs.map(tabToSnapshot)))
    } catch {
        // localStorage full or unavailable; tabs just won't survive a restart
    }
}

const getPersistedTabs = (): DesktopSceneTab[] | null => {
    try {
        const saved = localStorage.getItem(STORAGE_KEY)
        if (saved) {
            const parsed = JSON.parse(saved)
            if (Array.isArray(parsed) && parsed.length > 0) {
                return parsed.map((tab) => ({ ...tab, id: tab.id || generateTabId() }))
            }
        }
    } catch (e) {
        console.error('Failed to parse saved desktop tabs:', e)
    }
    return null
}

export const sceneTabsLogic = kea<sceneTabsLogicType>([
    path(['layout', 'scenes', 'sceneTabsLogic']),
    connect(() => ({
        // Mounts sceneLogic; its titleAndIcon selector is wrapped in sceneTitleAndIcon below
        // rather than connected as a value, because kea-typegen mangles the literal-union
        // type when copying it across logic type files
        logic: [sceneLogic],
        actions: [router, ['locationChanged']],
    })),
    actions({
        newTab: (href?: string | null, options?: { activate?: boolean; source?: TabOpenSource }) => ({
            href,
            options,
            tabId: generateTabId(),
        }),
        setTabs: (tabs: DesktopSceneTab[]) => ({ tabs }),
        activateTab: (tab: DesktopSceneTab) => ({ tab }),
        clickOnTab: (tab: DesktopSceneTab) => ({ tab }),
        closeTabId: (tabId: string, options?: { source?: TabCloseSource }) => ({ tabId, options }),
        removeTab: (tab: DesktopSceneTab, options?: { source?: TabCloseSource }) => ({ tab, options }),
        reorderTabs: (activeId: string, overId: string) => ({ activeId, overId }),
        duplicateTab: (tab: DesktopSceneTab) => ({ tab }),
        startTabEdit: (tab: DesktopSceneTab) => ({ tab }),
        endTabEdit: true,
        saveTabEdit: (tab: DesktopSceneTab, name: string) => ({ tab, name }),
        pinTab: (tabId: string) => ({ tabId }),
        unpinTab: (tabId: string) => ({ tabId }),
        applyTitleAndIcon: (title: string, iconType: DesktopSceneTab['iconType']) => ({ title, iconType }),
        setFrozenWidths: (widths: Record<string, number> | null) => ({ widths }),
        clearFrozenWidths: true,
        freezeTabWidths: true,
    }),
    reducers({
        tabs: [
            [] as DesktopSceneTab[],
            {
                setTabs: (_, { tabs }) => ensureActiveTab(sortTabsPinnedFirst(tabs)),
                newTab: (state, { href, options, tabId }) => {
                    const activate = options?.activate ?? true
                    const { pathname, search, hash } = combineUrl(href || urls.newTab())
                    const baseTabs = activate
                        ? state.map((tab) => (tab.active ? { ...tab, active: false } : tab))
                        : state
                    return sortTabsPinnedFirst([
                        ...baseTabs,
                        freshTab({
                            id: tabId,
                            active: activate,
                            pathname: addProjectIdIfMissing(pathname),
                            search,
                            hash,
                        }),
                    ])
                },
                removeTab: (state, { tab }) => {
                    const index = state.findIndex((t) => t.id === tab.id)
                    if (index === -1) {
                        return state
                    }
                    let newState = state.filter((_, i) => i !== index)
                    if (!newState.find((t) => t.active)) {
                        const newActiveIndex = Math.max(index - 1, 0)
                        newState = newState.map((t, i) => (i === newActiveIndex ? { ...t, active: true } : t))
                    }
                    if (newState.length === 0) {
                        newState.push(freshTab())
                    }
                    return ensureActiveTab(sortTabsPinnedFirst(newState))
                },
                activateTab: (state, { tab }) =>
                    sortTabsPinnedFirst(
                        state.map((t) =>
                            t.id === tab.id
                                ? t.active
                                    ? t
                                    : { ...t, active: true, badge: false }
                                : t.active
                                  ? { ...t, active: false }
                                  : t
                        )
                    ),
                reorderTabs: (state, { activeId, overId }) => {
                    const activeTab = state.find((t) => t.id === activeId)
                    const overTab = state.find((t) => t.id === overId)
                    if (!activeTab || !overTab || activeId === overId || !!activeTab.pinned !== !!overTab.pinned) {
                        return state
                    }
                    const { pinned, unpinned } = partitionTabs(state)
                    const group = activeTab.pinned ? pinned : unpinned
                    const from = group.findIndex((tab) => tab.id === activeId)
                    const to = group.findIndex((tab) => tab.id === overId)
                    if (from === -1 || to === -1 || from === to) {
                        return state
                    }
                    const reordered = arrayMove(group, from, to)
                    return activeTab.pinned ? [...reordered, ...unpinned] : [...pinned, ...reordered]
                },
                duplicateTab: (state, { tab }) => {
                    const source = state.find((t) => t.id === tab.id) ?? tab
                    const cloned = tabToSnapshot({ ...source, id: generateTabId(), active: false })
                    const sourceIndex = state.findIndex((t) => t.id === source.id)
                    const insertAt = sourceIndex === -1 ? state.length : sourceIndex + 1
                    return sortTabsPinnedFirst([...state.slice(0, insertAt), cloned, ...state.slice(insertAt)])
                },
                saveTabEdit: (state, { tab, name }) =>
                    state.map((t) => (t.id === tab.id ? { ...t, customTitle: name.trim() || undefined } : t)),
                applyTitleAndIcon: (state, { title, iconType }) =>
                    state.map((tab) => (tab.active ? { ...tab, title, iconType, badge: false } : tab)),
                pinTab: (state, { tabId }) => updateTabPinnedState(state, tabId, true),
                unpinTab: (state, { tabId }) => updateTabPinnedState(state, tabId, false),
            },
        ],
        editingTabId: [
            null as string | null,
            {
                startTabEdit: (_, { tab }) => tab.id,
                endTabEdit: () => null,
                saveTabEdit: () => null,
            },
        ],
        frozenWidths: [
            null as Record<string, number> | null,
            {
                setFrozenWidths: (_, { widths }) => widths,
                clearFrozenWidths: () => null,
            },
        ],
    }),
    selectors({
        sceneTitleAndIcon: [
            () => [sceneLogic.selectors.titleAndIcon],
            (titleAndIcon): { title: string; iconType: DesktopSceneTab['iconType'] } => titleAndIcon,
        ],
        activeTab: [
            (s) => [s.tabs],
            (tabs: DesktopSceneTab[]): DesktopSceneTab | null => tabs.find((tab) => tab.active) || tabs[0] || null,
        ],
        activeTabId: [
            (s) => [s.activeTab],
            (activeTab: DesktopSceneTab | null): string | null => activeTab?.id ?? null,
        ],
        firstTabIsActive: [
            (s) => [s.activeTabId, s.tabs],
            (activeTabId: string | null, tabs: DesktopSceneTab[]): boolean => activeTabId === tabs[0]?.id,
        ],
    }),
    listeners(({ actions, values }) => ({
        [NEW_INTERNAL_TAB]: (payload: { path?: string; source?: TabOpenSource }) => {
            // Background tab, matching what cmd/ctrl+click does in a browser
            actions.newTab(payload.path, { source: payload?.source ?? 'internal_link', activate: false })
        },
        newTab: ({ href, options, tabId }) => {
            const created = values.tabs.find((tab) => tab.id === tabId)
            posthog.capture('tab opened', {
                tab_id: tabId,
                pathname: created?.pathname,
                open_source: options?.source ?? 'unknown',
                desktop: true,
            })
            if (options?.activate ?? true) {
                router.actions.push(href || urls.newTab())
            }
        },
        clickOnTab: ({ tab }) => {
            if (!tab.active) {
                actions.activateTab(tab)
            }
            router.actions.push(tab.pathname, tab.search, tab.hash)
        },
        closeTabId: ({ tabId, options }) => {
            const tab = values.tabs.find(({ id }) => id === tabId)
            if (tab) {
                actions.removeTab(tab, options)
            }
        },
        removeTab: ({ tab, options }) => {
            posthog.capture('tab closed', {
                tab_id: tab.id,
                pathname: tab.pathname,
                close_source: options?.source ?? 'unknown',
                desktop: true,
            })
            if (tab.active) {
                // values.activeTab is already the newly activated neighbor from the reducer
                const { activeTab } = values
                if (activeTab) {
                    router.actions.push(activeTab.pathname, activeTab.search, activeTab.hash)
                }
            }
        },
        locationChanged: ({ pathname, search, hash }) => {
            const fullPathname = addProjectIdIfMissing(pathname)
            const activeIndex = values.tabs.findIndex((tab) => tab.active)
            if (activeIndex !== -1) {
                const active = values.tabs[activeIndex]
                if (active.pathname === fullPathname && active.search === search && active.hash === hash) {
                    return
                }
                actions.setTabs(
                    values.tabs.map((tab, i) =>
                        i === activeIndex ? { ...tab, pathname: fullPathname, search, hash } : tab
                    )
                )
            } else {
                actions.setTabs([
                    ...values.tabs,
                    freshTab({ pathname: fullPathname, search, hash, title: 'Loading...', iconType: 'loading' }),
                ])
            }
        },
        freezeTabWidths: () => {
            const tabRow = document.querySelector('.scene-tab-row')
            if (!tabRow) {
                return
            }
            const widths: Record<string, number> = {}
            tabRow.querySelectorAll<HTMLElement>('[data-tab-id]').forEach((el) => {
                const id = el.getAttribute('data-tab-id')
                if (id) {
                    widths[id] = el.getBoundingClientRect().width
                }
            })
            actions.setFrozenWidths(widths)
        },
    })),
    subscriptions(({ actions, values }) => ({
        sceneTitleAndIcon: ({ title, iconType }: { title: string; iconType: DesktopSceneTab['iconType'] }) => {
            if (!title || title === '...' || title === 'Loading...') {
                // While the scene is loading, don't flicker between the old title and a placeholder
                return
            }
            const active = values.tabs.find((tab) => tab.active)
            if (active && (active.title !== title || active.iconType !== iconType)) {
                actions.applyTitleAndIcon(title, iconType)
            }
        },
        tabs: (tabs: DesktopSceneTab[]) => {
            if (isDesktopApp() && tabs.length > 0) {
                persistTabs(tabs)
            }
        },
    })),
    afterMount(({ actions, values }) => {
        const { currentLocation } = router.values
        const currentTab = freshTab({
            pathname: addProjectIdIfMissing(currentLocation.pathname),
            search: currentLocation.search,
            hash: currentLocation.hash,
            title: 'Loading...',
            iconType: 'loading',
        })

        // The scene often finishes loading before this logic mounts (the tab strip lives
        // in a lazy chunk), in which case titleAndIcon never changes again — seed it.
        const seedTitle = (): void => {
            const { title, iconType } = values.sceneTitleAndIcon ?? {}
            if (title && title !== '...' && title !== 'Loading...') {
                actions.applyTitleAndIcon(title, iconType)
            }
        }

        const persisted = isDesktopApp() ? getPersistedTabs() : null
        if (!persisted) {
            actions.setTabs([currentTab])
            seedTitle()
            return
        }

        // Adopt the current location into the restored tab set: activate the matching tab,
        // otherwise point the previously active tab at where the app actually is.
        const restored = persisted.map((tab) => ({ ...tab, sceneParams: undefined }))
        const matchIndex = restored.findIndex(
            (tab) =>
                tab.pathname === currentTab.pathname &&
                (tab.search ?? '') === currentTab.search &&
                (tab.hash ?? '') === currentTab.hash
        )
        if (matchIndex !== -1) {
            actions.setTabs(restored.map((tab, i) => ({ ...tab, active: i === matchIndex })))
            seedTitle()
            return
        }
        const activeIndex = Math.max(
            restored.findIndex((tab) => tab.active),
            0
        )
        actions.setTabs(
            restored.map((tab, i) =>
                i === activeIndex
                    ? {
                          ...tab,
                          active: true,
                          pathname: currentTab.pathname,
                          search: currentTab.search,
                          hash: currentTab.hash,
                          title: 'Loading...',
                          iconType: 'loading' as const,
                          customTitle: undefined,
                      }
                    : { ...tab, active: false }
            )
        )
    }),
])
