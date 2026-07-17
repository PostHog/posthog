import { arrayMove } from '@dnd-kit/sortable'
import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { combineUrl, router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import { isDesktopApp, isDesktopFreshWindow } from 'lib/utils/isDesktopApp'
import { addProjectIdIfMissing } from 'lib/utils/kea-router'
import { NEW_INTERNAL_TAB } from 'lib/utils/newInternalTab'
import { sceneLogic } from 'scenes/sceneLogic'
import { SceneTab } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import type { InsightShortId } from '~/types'

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

interface TabKeepAliveEntry {
    /** Prefix for the keep-alive cache key */
    name: string
    /** Matched against the tab pathname; capture group 1 (when present) is the resource id */
    pattern: RegExp
    /** Skip transient ids like 'new' */
    skip?: (id: string) => boolean
    /** Lazy-imports the scene chunk and mounts the logic with the same key the scene builds; returns the unmount fn */
    mount: (id: string) => Promise<() => void>
}

/**
 * Tab-aware scenes: for every open tab that points at one of these resources, keep the scene's
 * root logic mounted, so its state (loaded data, local edits, filters) survives switching to
 * another tab and back — the scene itself remounts, but re-attaches to the still-mounted logic.
 * Chunks are lazy-imported only when a matching tab actually exists. Note: two tabs on the same
 * resource share one logic; state is per-resource, not per-tab.
 */
const TAB_KEEP_ALIVE: TabKeepAliveEntry[] = [
    {
        name: 'notebook',
        pattern: /\/notebooks\/([^/?#]+)$/,
        skip: (id) => id === 'new',
        mount: async (shortId) => {
            const [{ notebookLogic }, { NotebookTarget }] = await Promise.all([
                import('scenes/notebooks/Notebook/notebookLogic'),
                import('scenes/notebooks/types'),
            ])
            return notebookLogic({ shortId, target: NotebookTarget.Scene }).mount()
        },
    },
    {
        name: 'insight',
        pattern: /\/insights\/([^/?#]+)/,
        skip: (id) => id === 'new' || id.startsWith('new-'),
        mount: async (shortId) => {
            const { insightLogic } = await import('scenes/insights/insightLogic')
            // Bare dashboardItemId yields the same kea key the insight scene builds (no tabId/dashboardId)
            return insightLogic({ dashboardItemId: shortId as InsightShortId }).mount()
        },
    },
    {
        name: 'dashboard',
        pattern: /\/dashboard\/(\d+)/,
        mount: async (id) => {
            const { dashboardLogic } = await import('scenes/dashboard/dashboardLogic')
            return dashboardLogic({ id: parseInt(id) }).mount()
        },
    },
    {
        name: 'feature-flag',
        pattern: /\/feature_flags\/(\d+)/,
        mount: async (id) => {
            const { featureFlagLogic } = await import('scenes/feature-flags/featureFlagLogic')
            return featureFlagLogic({ id: parseInt(id) }).mount()
        },
    },
    {
        name: 'experiment',
        pattern: /\/experiments\/(\d+)/,
        mount: async (id) => {
            const { experimentLogic } = await import('scenes/experiments/experimentLogic')
            return experimentLogic({ experimentId: parseInt(id) }).mount()
        },
    },
    // List scenes are singleton logics: keeping them mounted preserves filters and loaded results
    {
        name: 'insights-list',
        pattern: /\/insights\/?$/,
        mount: async () => (await import('scenes/saved-insights/savedInsightsLogic')).savedInsightsLogic.mount(),
    },
    {
        name: 'dashboards-list',
        pattern: /\/dashboard\/?$/,
        mount: async () => (await import('scenes/dashboard/dashboards/dashboardsLogic')).dashboardsLogic.mount(),
    },
    {
        name: 'feature-flags-list',
        pattern: /\/feature_flags\/?$/,
        mount: async () => (await import('scenes/feature-flags/featureFlagsLogic')).featureFlagsLogic.mount(),
    },
    {
        name: 'experiments-list',
        pattern: /\/experiments\/?$/,
        mount: async () => (await import('scenes/experiments/experimentsLogic')).experimentsLogic.mount(),
    },
    {
        name: 'notebooks-list',
        pattern: /\/notebooks\/?$/,
        mount: async () =>
            (await import('scenes/notebooks/NotebooksTable/notebooksTableLogic')).notebooksTableLogic.mount(),
    },
]

const syncTabKeepAlive = (cache: Record<string, any>, tabs: DesktopSceneTab[]): void => {
    const keepAlive: Map<string, () => void> = (cache.tabKeepAlive ??= new Map())
    const wanted = new Map<string, { entry: TabKeepAliveEntry; id: string }>()
    for (const tab of tabs) {
        for (const entry of TAB_KEEP_ALIVE) {
            const match = tab.pathname.match(entry.pattern)
            if (!match) {
                continue
            }
            const id = match[1] ?? ''
            if (!entry.skip?.(id)) {
                wanted.set(`${entry.name}:${id}`, { entry, id })
            }
            break
        }
    }
    for (const [key, unmount] of keepAlive) {
        if (!wanted.has(key)) {
            keepAlive.delete(key)
            unmount()
        }
    }
    for (const [key, { entry, id }] of wanted) {
        if (!keepAlive.has(key)) {
            const placeholder = (): void => {}
            keepAlive.set(key, placeholder)
            void entry
                .mount(id)
                .then((unmount) => {
                    // Only keep the mount if the tab is still open and no newer sync raced us here
                    if (keepAlive.get(key) === placeholder) {
                        keepAlive.set(key, unmount)
                    } else {
                        unmount()
                    }
                })
                .catch(() => {
                    if (keepAlive.get(key) === placeholder) {
                        keepAlive.delete(key)
                    }
                })
        }
    }
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
        newTab: (href?: string | null, options?: { activate?: boolean; source?: TabOpenSource; title?: string }) => ({
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
                            // A title hint (e.g. the link text) beats "New tab" until the scene
                            // loads and reports its own title — background tabs never load at all
                            ...(options?.title ? { title: options.title, iconType: 'blank' as const } : {}),
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
        [NEW_INTERNAL_TAB]: (payload: {
            path?: string
            source?: TabOpenSource
            activate?: boolean
            title?: string
        }) => {
            // Background tab by default, matching what cmd/ctrl+click does in a browser;
            // explicit "open in new tab" menu items pass activate: true
            actions.newTab(payload.path, {
                source: payload?.source ?? 'internal_link',
                activate: payload?.activate ?? false,
                title: payload?.title,
            })
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
    subscriptions(({ actions, values, cache }) => ({
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
            // Additional ("fresh") windows don't persist: the primary window owns the saved tab set
            if (isDesktopApp() && !isDesktopFreshWindow() && tabs.length > 0) {
                persistTabs(tabs)
            }
            if (isDesktopApp()) {
                syncTabKeepAlive(cache, tabs)
            }
        },
    })),
    beforeUnmount(({ cache }) => {
        const keepAlive: Map<string, () => void> | undefined = cache.tabKeepAlive
        if (keepAlive) {
            for (const unmount of keepAlive.values()) {
                unmount()
            }
            keepAlive.clear()
        }
    }),
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

        // Windows opened via "open in new window" / File → New window start with just the
        // opened location plus the pinned tabs, instead of cloning the whole saved tab set
        if (isDesktopFreshWindow()) {
            const pinned = (persisted ?? [])
                .filter((tab) => tab.pinned)
                .map((tab) => ({ ...tab, sceneParams: undefined, active: false }))
            const matchIndex = pinned.findIndex(
                (tab) =>
                    tab.pathname === currentTab.pathname &&
                    (tab.search ?? '') === currentTab.search &&
                    (tab.hash ?? '') === currentTab.hash
            )
            if (matchIndex !== -1) {
                actions.setTabs(pinned.map((tab, i) => ({ ...tab, active: i === matchIndex })))
            } else {
                actions.setTabs([...pinned, currentTab])
            }
            seedTitle()
            return
        }

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
        // Scenes with static breadcrumbs finish before this lazy chunk mounts, so titleAndIcon
        // may never change again — seed it here or the tab stays "Loading..." forever
        seedTitle()
    }),
])
