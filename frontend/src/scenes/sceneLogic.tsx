import { arrayMove } from '@dnd-kit/sortable'
import equal from 'fast-deep-equal'
import { BuiltLogic, actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { combineUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import api from 'lib/api'
import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { BarStatus } from 'lib/components/CommandBar/types'
import { TeamMembershipLevel } from 'lib/constants'
import { trackFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getRelativeNextPath, identifierToHuman } from 'lib/utils'
import { getAppContext, getCurrentTeamIdOrNone } from 'lib/utils/getAppContext'
import { NEW_INTERNAL_TAB } from 'lib/utils/newInternalTab'
import { addProjectIdIfMissing, removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { withForwardedSearchParams } from 'lib/utils/sceneLogicUtils'
import {
    LoadedScene,
    Params,
    Scene,
    SceneConfig,
    SceneExport,
    SceneParams,
    SceneTab,
    sceneToAccessControlResourceType,
} from 'scenes/sceneTypes'
import {
    emptySceneParams,
    forwardedRedirectQueryParams,
    preloadedScenes,
    redirects,
    routes,
    sceneConfigurations,
} from 'scenes/scenes'
import { urls } from 'scenes/urls'

import type { FileSystemIconType } from '~/queries/schema/schema-general'
import { AccessControlLevel, OnboardingStepKey, ProductKey } from '~/types'

import { preflightLogic } from './PreflightCheck/preflightLogic'
import { handleLoginRedirect } from './authentication/loginLogic'
import { billingLogic } from './billing/billingLogic'
import { organizationLogic } from './organizationLogic'
import type { sceneLogicType } from './sceneLogicType'
import { inviteLogic } from './settings/organization/inviteLogic'
import { teamLogic } from './teamLogic'
import { userLogic } from './userLogic'

const TAB_STATE_KEY = 'scene-tabs-state'
const PINNED_TAB_STATE_KEY = 'scene-tabs-pinned-state'

interface PersistedPinnedState {
    tabs: SceneTab[]
    homepage: SceneTab | null
}

const getStorageKey = (key: string): string => {
    const teamId = getCurrentTeamIdOrNone()
    return `${key}-${teamId}`
}

const generateTabId = (): string => crypto?.randomUUID?.()?.split('-')?.pop() || `${Date.now()}-${Math.random()}`

const persistSessionTabs = (tabs: SceneTab[]): void => {
    sessionStorage.setItem(getStorageKey(TAB_STATE_KEY), JSON.stringify(tabs))
}

const getPersistedSessionTabs = (): SceneTab[] | null => {
    const savedTabs = sessionStorage.getItem(getStorageKey(TAB_STATE_KEY))
    if (savedTabs) {
        try {
            return JSON.parse(savedTabs)
        } catch (e) {
            console.error('Failed to parse saved tabs from sessionStorage:', e)
        }
    }
    return null
}

const sanitizeTabForPersistence = (tab: SceneTab): SceneTab => {
    const { active, ...rest } = tab
    return {
        ...rest,
        id: tab.id || generateTabId(),
        pinned: true,
        active: false,
    }
}

const persistPinnedTabs = (tabs: SceneTab[], homepage: SceneTab | null): void => {
    const pinnedTabs = getPinnedTabsForPersistence(tabs)
    const homepageTab = getHomepageForPersistence(homepage)

    const key = getStorageKey(PINNED_TAB_STATE_KEY)

    if (pinnedTabs.length === 0 && !homepageTab) {
        if (localStorage.getItem(key) !== null) {
            localStorage.removeItem(key)
        }
        return
    }

    const serialized = JSON.stringify({ personal: pinnedTabs, homepage: homepageTab })
    if (localStorage.getItem(key) !== serialized) {
        localStorage.setItem(key, serialized)
    }
}

const normalizeStoredPinnedTabs = (tabs: SceneTab[]): SceneTab[] =>
    tabs.map((tab) => {
        const sanitized: SceneTab = {
            ...tab,
            id: tab.id || generateTabId(),
            pinned: true,
            active: false,
        }
        return sanitized
    })

const normalizeStoredHomepage = (tab: SceneTab | Record<string, any> | null | undefined): SceneTab | null => {
    if (!tab || typeof tab !== 'object') {
        return null
    }

    return sanitizeTabForPersistence(tab as SceneTab)
}

const getPersistedPinnedState = (): PersistedPinnedState | null => {
    const savedTabs = localStorage.getItem(getStorageKey(PINNED_TAB_STATE_KEY))
    if (savedTabs) {
        try {
            const parsed = JSON.parse(savedTabs)
            let tabs: SceneTab[] = []
            let homepage: SceneTab | null = null

            if (Array.isArray(parsed)) {
                tabs = parsed
            } else if (parsed && typeof parsed === 'object') {
                if (Array.isArray(parsed.tabs)) {
                    tabs = parsed.tabs
                } else {
                    const personal = Array.isArray(parsed.personal) ? parsed.personal : []
                    const project = Array.isArray(parsed.project) ? parsed.project : []
                    tabs = [...personal, ...project]
                }

                homepage = normalizeStoredHomepage(parsed.homepage)
            }

            return {
                tabs: normalizeStoredPinnedTabs(tabs ?? []),
                homepage,
            }
        } catch (e) {
            console.error('Failed to parse saved tabs from localStorage:', e)
        }
    }
    return null
}

const persistTabs = (tabs: SceneTab[], homepage: SceneTab | null): void => {
    persistSessionTabs(tabs)
    persistPinnedTabs(tabs, homepage)
}

const getPinnedTabsForPersistence = (tabs: SceneTab[]): SceneTab[] => {
    const persisted: SceneTab[] = []
    for (const tab of tabs) {
        if (!tab.pinned) {
            continue
        }
        persisted.push(sanitizeTabForPersistence(tab))
    }
    return persisted
}

const getHomepageForPersistence = (homepage: SceneTab | null): SceneTab | null =>
    homepage ? sanitizeTabForPersistence(homepage) : null

const partitionTabs = (tabs: SceneTab[]): { pinned: SceneTab[]; unpinned: SceneTab[] } => {
    const pinned: SceneTab[] = []
    const unpinned: SceneTab[] = []
    for (const tab of tabs) {
        if (tab.pinned) {
            pinned.push({ ...tab, pinned: true })
        } else {
            unpinned.push({ ...tab, pinned: false })
        }
    }
    return { pinned, unpinned }
}

const sortTabsPinnedFirst = (tabs: SceneTab[]): SceneTab[] => {
    const { pinned, unpinned } = partitionTabs(tabs)
    return [...pinned, ...unpinned]
}

const updateTabPinnedState = (tabs: SceneTab[], tabId: string, pinned: boolean): SceneTab[] => {
    const index = tabs.findIndex((tab) => tab.id === tabId)
    if (index === -1) {
        return tabs
    }

    const newTabs = [...tabs]
    newTabs[index] = {
        ...tabs[index],
        pinned,
    }

    return ensureActiveTab(sortTabsPinnedFirst(newTabs))
}

const ensureActiveTab = (tabs: SceneTab[]): SceneTab[] => {
    if (!tabs.some((tab) => tab.active)) {
        if (tabs.length > 0) {
            tabs = tabs.map((tab, index) => ({ ...tab, active: index === 0 }))
        }
    }
    return tabs
}

const mergePinnedTabs = (storedPinned: PersistedPinnedState | null, fallbackPinned: SceneTab[]): SceneTab[] => {
    const storedTabs = storedPinned?.tabs ?? []

    if (storedTabs.length === 0) {
        return fallbackPinned.map((tab) => ({ ...tab, pinned: true }))
    }

    const activeById = new Map<string, boolean>()
    for (const tab of fallbackPinned) {
        activeById.set(tab.id, tab.active)
    }

    const normalized = storedTabs.map((tab) => {
        const id = tab.id || generateTabId()
        return {
            ...tab,
            id,
            pinned: true,
            active: activeById.get(id) ?? false,
        }
    })

    const existingIds = new Set(normalized.map((tab) => tab.id))
    for (const fallbackTab of fallbackPinned) {
        if (!existingIds.has(fallbackTab.id)) {
            normalized.push({ ...fallbackTab, pinned: true })
        }
    }

    return normalized
}

const composeTabsFromStorage = (storedPinned: PersistedPinnedState | null, baseTabs: SceneTab[]): SceneTab[] => {
    const { pinned: basePinned, unpinned } = partitionTabs(baseTabs)
    const mergedPinned = mergePinnedTabs(storedPinned, basePinned)
    return ensureActiveTab([...mergedPinned, ...unpinned.map((tab) => ({ ...tab, pinned: false }))])
}

export const productUrlMapping: Partial<Record<ProductKey, string[]>> = {
    [ProductKey.SESSION_REPLAY]: [urls.replay()],
    [ProductKey.FEATURE_FLAGS]: [urls.featureFlags(), urls.earlyAccessFeatures(), urls.experiments()],
    [ProductKey.SURVEYS]: [urls.surveys()],
    [ProductKey.PRODUCT_ANALYTICS]: [urls.insights()],
    [ProductKey.DATA_WAREHOUSE]: [urls.sqlEditor(), urls.dataPipelines('sources'), urls.dataWarehouseSourceNew()],
    [ProductKey.WEB_ANALYTICS]: [urls.webAnalytics()],
    [ProductKey.ERROR_TRACKING]: [urls.errorTracking()],
}

const productsNotDependingOnEventIngestion: ProductKey[] = [ProductKey.DATA_WAREHOUSE]

const pathPrefixesOnboardingNotRequiredFor = [
    urls.onboarding(''),
    urls.products(),
    '/settings',
    urls.organizationBilling(),
    urls.billingAuthorizationStatus(),
    urls.wizard(),
    '/instance',
    urls.moveToPostHogCloud(),
    urls.unsubscribe(),
    urls.debugHog(),
    urls.debugQuery(),
    urls.activity(),
    urls.oauthAuthorize(),
]

const DelayedLoadingSpinner = (): JSX.Element => {
    const [show, setShow] = useState(false)
    useEffect(() => {
        const timeout = window.setTimeout(() => setShow(true), 500)
        return () => window.clearTimeout(timeout)
    }, [])
    return <>{show ? <Spinner /> : null}</>
}

export const sceneLogic = kea<sceneLogicType>([
    props(
        {} as {
            scenes?: Record<string, () => any>
        }
    ),
    path(['scenes', 'sceneLogic']),

    connect(() => ({
        logic: [router, userLogic, preflightLogic],
        actions: [
            router,
            ['locationChanged', 'push'],
            commandBarLogic,
            ['setCommandBar'],
            inviteLogic,
            ['hideInviteModal'],
        ],
        values: [
            billingLogic,
            ['billing'],
            organizationLogic,
            ['organizationBeingDeleted'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    })),
    afterMount(({ cache }) => {
        cache.mountedTabLogic = {} as Record<string, () => void>
        cache.lastTrackedSceneByTab = {} as Record<string, { sceneId?: string; sceneKey?: string }>
        cache.initialNavigationTabCreated = false
    }),
    actions({
        /* 1. Prepares to open the scene, as the listener may override and do something
        else (e.g. redirecting if unauthenticated), then calls (2) `loadScene`*/
        openScene: (
            sceneId: string,
            sceneKey: string | undefined,
            tabId: string,
            params: SceneParams,
            method: string
        ) => ({
            sceneId,
            sceneKey,
            params,
            method,
            tabId,
        }),
        // 2. Start loading the scene's Javascript and mount any logic, then calls (3) `setScene`
        loadScene: (
            sceneId: string,
            sceneKey: string | undefined,
            tabId: string,
            params: SceneParams,
            method: string
        ) => ({
            sceneId,
            sceneKey,
            params,
            method,
            tabId,
        }),
        // 3. Set the `scene` reducer
        setScene: (
            sceneId: string,
            sceneKey: string | undefined,
            tabId: string,
            params: SceneParams,
            scrollToTop: boolean = false,
            exportedScene?: SceneExport
        ) => ({
            sceneId,
            sceneKey,
            tabId,
            params,
            scrollToTop,
            exportedScene,
        }),
        setExportedScene: (
            exportedScene: SceneExport,
            sceneId: string,
            sceneKey: string | undefined,
            tabId: string,
            params: SceneParams
        ) => ({
            exportedScene,
            sceneId,
            sceneKey,
            tabId,
            params,
        }),
        reloadBrowserDueToImportError: true,

        newTab: (href?: string | null, options?: { activate?: boolean; skipNavigate?: boolean; id?: string }) => ({
            href,
            options,
        }),
        setTabs: (tabs: SceneTab[]) => ({ tabs }),
        loadPinnedTabsFromBackend: true,
        setPinnedStateFromBackend: (pinnedState: PersistedPinnedState) => ({ pinnedState }),
        setHomepage: (tab: SceneTab | null) => ({ tab }),
        closeTabId: (tabId: string) => ({ tabId }),
        removeTab: (tab: SceneTab) => ({ tab }),
        activateTab: (tab: SceneTab) => ({ tab }),
        clickOnTab: (tab: SceneTab) => ({ tab }),
        reorderTabs: (activeId: string, overId: string) => ({ activeId, overId }),
        duplicateTab: (tab: SceneTab) => ({ tab }),
        renameTab: (tab: SceneTab) => ({ tab }),
        startTabEdit: (tab: SceneTab) => ({ tab }),
        endTabEdit: true,
        saveTabEdit: (tab: SceneTab, name: string) => ({ tab, name }),
        pinTab: (tabId: string) => ({ tabId }),
        unpinTab: (tabId: string) => ({ tabId }),
    }),
    reducers({
        // We store all state in "tabs". This allows us to have multiple tabs open, each with its own scene and parameters.
        tabs: [
            [] as SceneTab[],
            {
                setTabs: (_, { tabs }) => ensureActiveTab(sortTabsPinnedFirst(tabs)),
                setPinnedStateFromBackend: (state, { pinnedState }) => {
                    return composeTabsFromStorage(pinnedState, state)
                },
                newTab: (state, { href, options }) => {
                    const activate = options?.activate ?? true
                    const tabId = options?.id ?? generateTabId()
                    const { pathname, search, hash } = combineUrl(href || '/new')
                    const baseTabs = activate
                        ? state.map((tab) => (tab.active ? { ...tab, active: false } : tab))
                        : state
                    const newTab: SceneTab = {
                        id: tabId,
                        active: activate,
                        pathname: addProjectIdIfMissing(pathname),
                        search,
                        hash,
                        title: 'New tab',
                        iconType: 'blank',
                        pinned: false,
                    }
                    return sortTabsPinnedFirst([...baseTabs, newTab])
                },
                removeTab: (state, { tab }) => {
                    let index = state.findIndex((t) => t === tab)
                    if (index === -1) {
                        console.error('Tab to remove not found', tab)
                        return state
                    }
                    let newState = state.filter((_, i) => i !== index)
                    if (!newState.find((t) => t.active)) {
                        const newActiveIndex = Math.max(index - 1, 0)
                        newState = newState.map((tab, i) => (i === newActiveIndex ? { ...tab, active: true } : tab))
                    }
                    if (newState.length === 0) {
                        newState.push({
                            id: generateTabId(),
                            active: true,
                            pathname: '/new',
                            search: '',
                            hash: '',
                            title: 'New tab',
                            iconType: 'blank',
                            pinned: false,
                        })
                    }
                    return ensureActiveTab(sortTabsPinnedFirst(newState))
                },
                activateTab: (state, { tab }) => {
                    const newState = state.map((t) =>
                        t === tab
                            ? !t.active
                                ? { ...t, active: true }
                                : t
                            : t.active
                              ? {
                                    ...t,
                                    active: false,
                                }
                              : t
                    )
                    return sortTabsPinnedFirst(newState)
                },
                reorderTabs: (state, { activeId, overId }) => {
                    const activeIndex = state.findIndex((t) => t.id === activeId)
                    const overIndex = state.findIndex((t) => t.id === overId)
                    if (activeIndex === -1 || overIndex === -1 || activeIndex === overIndex) {
                        return state
                    }

                    const activeTab = state[activeIndex]
                    const overTab = state[overIndex]
                    if (!!activeTab?.pinned !== !!overTab?.pinned) {
                        return state
                    }

                    const { pinned, unpinned } = partitionTabs(state)

                    if (activeTab?.pinned && overTab?.pinned) {
                        const from = pinned.findIndex((tab) => tab.id === activeId)
                        const to = pinned.findIndex((tab) => tab.id === overId)
                        if (from === -1 || to === -1 || from === to) {
                            return state
                        }
                        const reordered = arrayMove(pinned, from, to)
                        return [...reordered, ...unpinned]
                    }

                    const from = unpinned.findIndex((tab) => tab.id === activeId)
                    const to = unpinned.findIndex((tab) => tab.id === overId)
                    if (from === -1 || to === -1 || from === to) {
                        return state
                    }
                    const newUnpinned = arrayMove(unpinned, from, to)
                    return [...pinned, ...newUnpinned]
                },
                duplicateTab: (state, { tab }) => {
                    const idx = state.findIndex((t) => t === tab || t.id === tab.id)
                    const source = idx !== -1 ? state[idx] : tab

                    const cloned: SceneTab = {
                        id: generateTabId(),
                        pathname: source.pathname,
                        search: source.search,
                        hash: source.hash,
                        title: source.title,
                        customTitle: source.customTitle,
                        iconType: source.iconType,
                        active: false,
                        pinned: !!source.pinned,
                    }

                    const { pinned, unpinned } = partitionTabs(state)

                    if (cloned.pinned) {
                        const sourceIndex = pinned.findIndex((t) => t.id === source.id)
                        const sanitizedCloned = { ...cloned, pinned: true }
                        const updated =
                            sourceIndex === -1
                                ? [...pinned, sanitizedCloned]
                                : [
                                      ...pinned.slice(0, sourceIndex + 1),
                                      sanitizedCloned,
                                      ...pinned.slice(sourceIndex + 1),
                                  ]
                        return [...updated, ...unpinned]
                    }

                    const sourceIndex = unpinned.findIndex((t) => t.id === source.id)
                    const sanitizedCloned = { ...cloned, pinned: false }
                    const newUnpinned =
                        sourceIndex === -1
                            ? [...unpinned, sanitizedCloned]
                            : [
                                  ...unpinned.slice(0, sourceIndex + 1),
                                  sanitizedCloned,
                                  ...unpinned.slice(sourceIndex + 1),
                              ]
                    return [...pinned, ...newUnpinned]
                },
                saveTabEdit: (state, { tab, name }) => {
                    return state.map((t) =>
                        t.id === tab.id
                            ? {
                                  ...t,
                                  customTitle: name.trim() === '' ? undefined : name.trim(),
                              }
                            : t
                    )
                },
                setScene: (state, { sceneId, sceneKey, tabId, params }) => {
                    return state.map((tab) =>
                        tab.id === tabId
                            ? {
                                  ...tab,
                                  sceneId: sceneId,
                                  sceneKey: sceneKey ?? undefined,
                                  sceneParams: params,
                              }
                            : tab
                    )
                },
                setExportedScene: (state, { sceneId, sceneKey, tabId, params }) => {
                    return state.map((tab) =>
                        tab.id === tabId
                            ? {
                                  ...tab,
                                  sceneId: sceneId,
                                  sceneKey: sceneKey,
                                  sceneParams: params,
                              }
                            : tab
                    )
                },
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
        exportedScenes: [
            preloadedScenes,
            {
                setExportedScene: (state, { exportedScene, sceneId }) => ({
                    ...state,
                    [sceneId]: { ...exportedScene },
                }),
            },
        ],
        loadingScene: [
            null as string | null,
            {
                loadScene: (_, { sceneId }) => sceneId,
                setScene: () => null,
            },
        ],
        lastReloadAt: [
            null as number | null,
            { persist: true },
            {
                reloadBrowserDueToImportError: () => new Date().valueOf(),
            },
        ],
        lastSetScenePayload: [
            {} as Record<string, any>,
            {
                setScene: (_, { sceneId, sceneKey, tabId, params }) => ({ sceneId, sceneKey, tabId, params }),
            },
        ],
    }),
    reducers({
        homepage: [
            null as SceneTab | null,
            {
                setPinnedStateFromBackend: (_, { pinnedState }) => pinnedState.homepage ?? null,
                setHomepage: (_, { tab }) => (tab ? sanitizeTabForPersistence(tab) : null),
            },
        ],
    }),
    selectors({
        activeTab: [
            (s) => [s.tabs],
            (tabs: SceneTab[]): SceneTab | null => {
                return tabs.find((tab) => tab.active) || tabs[0] || null
            },
        ],
        activeTabId: [
            (s) => [s.activeTab],
            (activeTab: SceneTab | null): string | null => (activeTab ? activeTab.id : null),
        ],
        sceneId: [(s) => [s.activeTab], (activeTab) => activeTab?.sceneId],
        sceneKey: [(s) => [s.activeTab], (activeTab) => activeTab?.sceneKey],
        sceneConfig: [
            (s) => [s.sceneId],
            (sceneId: Scene): SceneConfig | null => {
                const config = sceneConfigurations[sceneId] || null
                if (sceneId === Scene.SQLEditor) {
                    return { ...config, layout: 'app-raw' }
                }
                return config
            },
            { resultEqualityCheck: equal },
        ],
        sceneParams: [
            (s) => [s.activeTab],
            (activeTab): SceneParams => {
                return activeTab?.sceneParams || { params: {}, searchParams: {}, hashParams: {} }
            },
        ],
        activeSceneId: [
            (s) => [s.sceneId, teamLogic.selectors.isCurrentTeamUnavailable],
            (sceneId, isCurrentTeamUnavailable) => {
                const effectiveResourceAccessControl = getAppContext()?.effective_resource_access_control

                // Get the access control resource type for the current scene
                const sceneAccessControlResource = sceneId ? sceneToAccessControlResourceType[sceneId as Scene] : null

                // Check if the user has effective access to this resource (includes specific object access)
                if (
                    sceneAccessControlResource &&
                    effectiveResourceAccessControl &&
                    effectiveResourceAccessControl[sceneAccessControlResource] === AccessControlLevel.None
                ) {
                    return Scene.ErrorAccessDenied
                }

                // Check if the current team is unavailable for project-based scenes
                // Allow settings and danger zone to be opened
                if (
                    isCurrentTeamUnavailable &&
                    sceneId &&
                    sceneConfigurations[sceneId]?.projectBased &&
                    !location.pathname.startsWith('/settings') &&
                    location.pathname !== urls.settings('user-danger-zone')
                ) {
                    return Scene.ErrorProjectUnavailable
                }

                return sceneId
            },
        ],
        activeExportedScene: [
            (s) => [s.activeSceneId, s.exportedScenes],
            (activeSceneId, exportedScenes) => {
                return activeSceneId ? exportedScenes[activeSceneId] : null
            },
            { resultEqualityCheck: (a, b) => a === b },
        ],
        activeLoadedScene: [
            (s) => [s.activeSceneId, s.activeExportedScene, s.sceneParams, s.activeTabId],
            (activeSceneId, activeExportedScene, sceneParams, activeTabId): LoadedScene | null => {
                return {
                    ...(activeExportedScene ?? { component: DelayedLoadingSpinner }),
                    id: activeSceneId ?? Scene.Error404,
                    tabId: activeTabId ?? undefined,
                    sceneParams: sceneParams,
                }
            },
        ],
        activeSceneComponentParamsWithTabId: [
            (s) => [s.sceneParams, s.activeTabId],
            (sceneParams, activeTabId): Record<string, any> => {
                return {
                    ...sceneParams.params,
                    tabId: activeTabId,
                }
            },
            { resultEqualityCheck: equal },
        ],
        activeSceneLogicPropsWithTabId: [
            (s) => [s.activeExportedScene, s.sceneParams, s.activeTabId],
            (activeExportedScene, sceneParams, activeTabId): Record<string, any> => {
                return {
                    ...activeExportedScene?.paramsToProps?.(sceneParams),
                    tabId: activeTabId,
                }
            },
            { resultEqualityCheck: equal },
        ],
        activeSceneLogic: [
            (s) => [s.activeExportedScene, s.activeSceneLogicPropsWithTabId],
            (activeExportedScene, activeSceneLogicPropsWithTabId): BuiltLogic | null => {
                if (activeExportedScene?.logic) {
                    return activeExportedScene.logic.build(activeSceneLogicPropsWithTabId)
                }

                return null
            },
        ],
        searchParams: [(s) => [s.sceneParams], (sceneParams): Record<string, any> => sceneParams.searchParams || {}],
        hashParams: [(s) => [s.sceneParams], (sceneParams): Record<string, any> => sceneParams.hashParams || {}],
        productFromUrl: [
            () => [router.selectors.location],
            (location: Location): ProductKey | null => {
                const pathname = location.pathname
                for (const [productKey, urls] of Object.entries(productUrlMapping)) {
                    if (urls.some((url) => pathname.includes(url))) {
                        return productKey as ProductKey
                    }
                }
                return null
            },
        ],

        tabIds: [
            (s) => [s.tabs],
            (tabs: SceneTab[]): Record<string, boolean> => {
                return tabs.reduce(
                    (acc, tab) => {
                        acc[tab.id] = true
                        return acc
                    },
                    {} as Record<string, boolean>
                )
            },
        ],

        titleAndIcon: [
            (s) => [
                // We're effectively passing the selector through to the scene logic, and "recalculating"
                // this every time it's rendered. Caching will happen within the scene's breadcrumb selector.
                (state, props): { title: string; iconType: FileSystemIconType | 'loading' | 'blank' } => {
                    const activeSceneLogic = sceneLogic.selectors.activeSceneLogic(state, props)
                    const activeExportedScene = sceneLogic.selectors.activeExportedScene(state, props)
                    if (activeSceneLogic && 'breadcrumbs' in activeSceneLogic.selectors) {
                        try {
                            const sceneParams = sceneLogic.selectors.sceneParams(state, props)
                            const bc = activeSceneLogic.selectors.breadcrumbs(
                                state,
                                activeExportedScene?.paramsToProps?.(sceneParams) || props
                            )
                            return {
                                title: bc.length > 0 ? bc[bc.length - 1].name : '...',
                                iconType: bc.length > 0 ? bc[bc.length - 1].iconType : 'blank',
                            }
                        } catch {
                            // If the breadcrumb selector fails, we'll just ignore it and return a placeholder value below
                        }
                    }

                    const activeSceneId = s.activeSceneId(state, props)
                    if (activeSceneId) {
                        const sceneConfig = s.sceneConfig(state, props)
                        return {
                            title: sceneConfig?.name ?? identifierToHuman(activeSceneId),
                            iconType: sceneConfig?.iconType ?? (activeExportedScene ? 'notebook' : 'loading'),
                        }
                    }
                    return { title: '...', iconType: 'loading' }
                },
            ],
            (titleAndIcon) => titleAndIcon as { title: string; iconType: FileSystemIconType | 'loading' | 'blank' },
            { resultEqualityCheck: equal },
        ],
    }),
    listeners(({ values, actions, cache, props, selectors }) => ({
        [NEW_INTERNAL_TAB]: (payload) => {
            actions.newTab(payload.path)
        },
        newTab: ({ href, options }) => {
            persistTabs(values.tabs, values.homepage)
            if (!(options?.skipNavigate ?? false)) {
                router.actions.push(href || urls.newTab())
            }
        },
        setTabs: () => persistTabs(values.tabs, values.homepage),
        activateTab: () => persistTabs(values.tabs, values.homepage),
        duplicateTab: () => persistTabs(values.tabs, values.homepage),
        renameTab: ({ tab }) => {
            actions.startTabEdit(tab)
        },
        pinTab: () => persistTabs(values.tabs, values.homepage),
        unpinTab: ({ tabId }) => {
            if (values.homepage?.id === tabId) {
                actions.setHomepage(null)
            } else {
                persistTabs(values.tabs, values.homepage)
            }
        },
        loadPinnedTabsFromBackend: async () => {
            try {
                const response = await api.get<{
                    tabs?: SceneTab[]
                    homepage?: SceneTab | null
                }>('api/user_pinned_scene_tabs/@me/')
                const tabs = response?.tabs ?? []
                const homepage = response?.homepage ?? null
                cache.skipNextPinnedSync = true
                const pinnedState: PersistedPinnedState = {
                    tabs: normalizeStoredPinnedTabs(tabs),
                    homepage: homepage ? sanitizeTabForPersistence(homepage) : null,
                }
                actions.setPinnedStateFromBackend(pinnedState)
            } catch (error) {
                console.error('Failed to load pinned scene tabs', error)
            }
        },
        setPinnedStateFromBackend: () => {
            persistTabs(values.tabs, values.homepage)
        },
        setHomepage: () => {
            persistTabs(values.tabs, values.homepage)
        },
        closeTabId: ({ tabId }) => {
            const tab = values.tabs.find(({ id }) => id === tabId)
            if (tab) {
                actions.removeTab(tab)
            }
        },
        removeTab: ({ tab }) => {
            const isHomepageTab = values.homepage?.id === tab.id
            if (tab.active) {
                // values.activeTab will already be the new active tab from the reducer
                const { activeTab } = values
                if (activeTab) {
                    router.actions.push(activeTab.pathname, activeTab.search, activeTab.hash)
                } else if (!isHomepageTab) {
                    persistTabs(values.tabs, values.homepage)
                }
            } else if (!isHomepageTab) {
                persistTabs(values.tabs, values.homepage)
            }

            if (isHomepageTab) {
                actions.setHomepage(null)
            }
        },
        clickOnTab: ({ tab }) => {
            if (!tab.active) {
                actions.activateTab(tab)
            }
            router.actions.push(tab.pathname, tab.search, tab.hash)
            persistTabs(values.tabs, values.homepage)
        },
        reorderTabs: () => {
            persistTabs(values.tabs, values.homepage)
        },
        push: ({ url, hashInput, searchInput }) => {
            let { pathname, search, hash } = combineUrl(url, searchInput, hashInput)
            pathname = addProjectIdIfMissing(pathname)

            const activeTabIndex = values.tabs.findIndex((tab) => tab.active)
            if (activeTabIndex !== -1) {
                const newTabs = values.tabs.map((tab, i) =>
                    i === activeTabIndex
                        ? { ...tab, active: true, pathname, search, hash }
                        : tab.active
                          ? {
                                ...tab,
                                active: false,
                            }
                          : tab
                )
                actions.setTabs(newTabs)
            } else {
                actions.setTabs([
                    ...values.tabs,
                    {
                        id: generateTabId(),
                        active: true,
                        pathname,
                        search,
                        hash,
                        title: 'Loading...',
                        iconType: 'loading',
                        pinned: false,
                    },
                ])
            }
            persistTabs(values.tabs, values.homepage)
        },
        locationChanged: ({ pathname, search, hash, routerState, method }) => {
            pathname = addProjectIdIfMissing(pathname)
            if (routerState?.tabs && method === 'POP') {
                actions.setTabs(routerState.tabs)
                return
            }
            const activeTabIndex = values.tabs.findIndex((tab) => tab.active)
            if (activeTabIndex !== -1) {
                actions.setTabs(
                    values.tabs.map((tab, i) =>
                        i === activeTabIndex
                            ? { ...tab, active: true, pathname, search, hash }
                            : tab.active
                              ? {
                                    ...tab,
                                    active: false,
                                }
                              : tab
                    )
                )
            } else {
                actions.setTabs([
                    ...values.tabs,
                    {
                        id: generateTabId(),
                        active: true,
                        pathname,
                        search,
                        hash,
                        title: 'Loading...',
                        iconType: 'loading',
                        pinned: false,
                    },
                ])
            }
            persistTabs(values.tabs, values.homepage)

            // Open search or command bar
            const params = new URLSearchParams(search)
            const searchBar = params.get('searchBar')
            const commandBar = params.get('commandBar')

            if (searchBar !== null) {
                actions.setCommandBar(BarStatus.SHOW_SEARCH, searchBar)
                params.delete('searchBar')
                router.actions.replace(pathname, params, hash)
            } else if (commandBar !== null) {
                actions.setCommandBar(BarStatus.SHOW_ACTIONS, commandBar)
                params.delete('commandBar')
                router.actions.replace(pathname, params, hash)
            }

            // Remove trailing slash
            if (pathname !== '/' && pathname.endsWith('/')) {
                router.actions.replace(pathname.replace(/(\/+)$/, ''), search, hash)
            }
        },
        setScene: ({ tabId, sceneKey, sceneId, exportedScene, params, scrollToTop }, _, __, previousState) => {
            const {
                sceneId: lastSceneId,
                sceneKey: lastSceneKey,
                tabId: lastTabId,
                params: lastParams,
            } = selectors.lastSetScenePayload(previousState)

            // Do not trigger a new pageview event when only the hashParams change
            if (
                lastSceneId !== sceneId ||
                lastSceneKey !== sceneKey ||
                lastTabId !== tabId ||
                !equal(lastParams.params, params.params) ||
                JSON.stringify(lastParams.searchParams) !== JSON.stringify(params.searchParams) // `equal` crashes here
            ) {
                posthog.capture('$pageview')
            }

            // if we clicked on a link, scroll to top
            const previousScene = selectors.sceneId(previousState)
            if (scrollToTop && sceneId !== previousScene) {
                window.scrollTo(0, 0)
            }

            const unmount = cache.mountedTabLogic[tabId]
            if (unmount) {
                window.setTimeout(unmount, 50)
                delete cache.mountedTabLogic[tabId]
            }
            if (exportedScene?.logic) {
                const builtLogicProps = { tabId, ...exportedScene?.paramsToProps?.(params) }
                const builtLogic = exportedScene?.logic(builtLogicProps)
                cache.mountedTabLogic[tabId] = builtLogic.mount()
            }

            const trackingKey = tabId || '__default__'
            const lastTracked = cache.lastTrackedSceneByTab?.[trackingKey]
            if (!lastTracked || lastTracked.sceneId !== sceneId || lastTracked.sceneKey !== sceneKey) {
                trackFileSystemLogView({ type: 'scene', ref: sceneId })
                cache.lastTrackedSceneByTab[trackingKey] = { sceneId, sceneKey }
            }
        },
        openScene: ({ tabId, sceneId, sceneKey, params, method }) => {
            const sceneConfig = sceneConfigurations[sceneId] || {}
            const { user } = userLogic.values
            const { preflight } = preflightLogic.values

            if (sceneId === Scene.Signup && preflight && !preflight.can_create_org) {
                // If user is on an already initiated self-hosted instance, redirect away from signup
                router.actions.replace(urls.login())
                return
            }
            if (sceneId === Scene.Login && preflight?.demo) {
                // In the demo environment, there's only passwordless "login" via the signup scene
                router.actions.replace(urls.signup())
                return
            }
            if (sceneId === Scene.MoveToPostHogCloud && preflight?.cloud) {
                router.actions.replace(urls.projectHomepage())
                return
            }

            if (user) {
                // If user is already logged in, redirect away from unauthenticated-only routes (e.g. /signup)
                if (sceneConfig.onlyUnauthenticated) {
                    if (sceneId === Scene.Login) {
                        handleLoginRedirect()
                    } else {
                        router.actions.replace(urls.default())
                    }
                    return
                }

                // Redirect to org/project creation if there's no org/project respectively, unless using invite
                if (sceneId !== Scene.InviteSignup) {
                    if (organizationLogic.values.isCurrentOrganizationUnavailable) {
                        if (
                            location.pathname !== urls.organizationCreateFirst() &&
                            location.pathname !== urls.settings('user-danger-zone')
                        ) {
                            console.warn('Organization not available, redirecting to organization creation')
                            router.actions.replace(urls.organizationCreateFirst())
                            return
                        }
                    } else if (teamLogic.values.isCurrentTeamUnavailable) {
                        if (
                            user.organization?.teams.length === 0 &&
                            user.organization.membership_level &&
                            user.organization.membership_level >= TeamMembershipLevel.Admin
                        ) {
                            // Allow settings to be opened, otherwise route to project creation
                            if (
                                location.pathname !== urls.projectCreateFirst() &&
                                !location.pathname.startsWith('/settings')
                            ) {
                                console.warn(
                                    'Project not available and no other projects, redirecting to project creation'
                                )
                                lemonToast.error('You do not have access to any projects in this organization', {
                                    toastId: 'no-projects',
                                })
                                router.actions.replace(urls.projectCreateFirst())
                                return
                            }
                        }
                    } else if (
                        teamLogic.values.currentTeam &&
                        !teamLogic.values.currentTeam.is_demo &&
                        !pathPrefixesOnboardingNotRequiredFor.some((path) =>
                            removeProjectIdIfPresent(location.pathname).startsWith(path)
                        )
                    ) {
                        const allProductUrls = Object.values(productUrlMapping).flat()
                        const productKeyFromUrl = Object.keys(productUrlMapping).find((key) =>
                            productUrlMapping[key as ProductKey]?.some(
                                (path: string) =>
                                    removeProjectIdIfPresent(location.pathname).startsWith(path) &&
                                    !path.startsWith('/projects')
                            )
                        )
                        if (!productsNotDependingOnEventIngestion.includes(productKeyFromUrl as ProductKey)) {
                            if (
                                !teamLogic.values.hasOnboardedAnyProduct &&
                                !allProductUrls.some((path) =>
                                    removeProjectIdIfPresent(location.pathname).startsWith(path)
                                ) &&
                                !teamLogic.values.currentTeam?.ingested_event
                            ) {
                                console.warn('No onboarding completed, redirecting to /products')

                                const nextUrl =
                                    getRelativeNextPath(params.searchParams.next, location) ??
                                    removeProjectIdIfPresent(location.pathname)

                                router.actions.replace(urls.products(), nextUrl ? { next: nextUrl } : undefined)
                                return
                            }

                            if (
                                productKeyFromUrl &&
                                teamLogic.values.currentTeam &&
                                !teamLogic.values.currentTeam?.has_completed_onboarding_for?.[productKeyFromUrl]
                                // cloud mode? What is the experience for self-hosted?
                            ) {
                                if (
                                    !teamLogic.values.hasOnboardedAnyProduct &&
                                    !teamLogic.values.currentTeam?.ingested_event
                                ) {
                                    console.warn(
                                        `Onboarding not completed for ${productKeyFromUrl}, redirecting to onboarding intro`
                                    )

                                    router.actions.replace(
                                        urls.onboarding(productKeyFromUrl, OnboardingStepKey.INSTALL)
                                    )
                                    return
                                }
                            }
                        }
                    }
                }
            }

            actions.loadScene(sceneId, sceneKey, tabId, params, method)
        },
        loadScene: async ({ sceneId, sceneKey, tabId, params, method }, breakpoint) => {
            const clickedLink = method === 'PUSH'
            if (values.sceneId === sceneId && values.exportedScenes[sceneId]) {
                actions.setScene(sceneId, sceneKey, tabId, params, clickedLink, values.exportedScenes[sceneId])
                return
            }

            if (!props.scenes?.[sceneId]) {
                actions.setScene(
                    Scene.Error404,
                    undefined,
                    tabId,
                    emptySceneParams,
                    clickedLink,
                    values.exportedScenes[sceneId]
                )
                return
            }

            let exportedScene = values.exportedScenes[sceneId]
            const wasNotLoaded = !exportedScene

            if (!exportedScene) {
                // if we can't load the scene in a second, show a spinner
                const timeout = window.setTimeout(() => actions.setScene(sceneId, sceneKey, tabId, params, true), 500)
                let importedScene
                try {
                    window.ESBUILD_LOAD_CHUNKS?.(sceneId)
                    importedScene = await props.scenes[sceneId]()
                } catch (error: any) {
                    if (
                        error.name === 'ChunkLoadError' || // webpack
                        error.message?.includes('Failed to fetch dynamically imported module') // esbuild
                    ) {
                        // Reloaded once in the last 20 seconds and now reloading again? Show network error
                        if (
                            values.lastReloadAt &&
                            parseInt(String(values.lastReloadAt)) > new Date().valueOf() - 20000
                        ) {
                            console.error('App assets regenerated. Showing error page.')
                            actions.setScene(Scene.ErrorNetwork, undefined, tabId, emptySceneParams, clickedLink)
                        } else {
                            console.error('App assets regenerated. Reloading this page.')
                            actions.reloadBrowserDueToImportError()
                        }
                        return
                    }
                    throw error
                } finally {
                    window.clearTimeout(timeout)
                }
                if (values.sceneId !== sceneId) {
                    breakpoint()
                }
                const { default: defaultExport, logic, scene: _scene, ...others } = importedScene

                if (_scene) {
                    exportedScene = _scene
                } else if (defaultExport) {
                    console.warn(`Scene ${sceneId} not yet converted to use SceneExport!`)
                    exportedScene = {
                        component: defaultExport,
                        logic: logic,
                    }
                } else {
                    console.warn(`Scene ${sceneId} not yet converted to use SceneExport!`)
                    exportedScene = {
                        component:
                            Object.keys(others).length === 1
                                ? others[Object.keys(others)[0]]
                                : values.exportedScenes[Scene.Error404].component,
                        logic: logic,
                    }
                    if (Object.keys(others).length > 1) {
                        console.error('There are multiple exports for this scene. Showing 404 instead.')
                    }
                }
                actions.setExportedScene(exportedScene, sceneId, sceneKey, tabId, params)

                if (exportedScene.logic) {
                    // initialize the logic and give it 50ms to load before opening the scene
                    const props = { ...exportedScene.paramsToProps?.(params), tabId }
                    const unmount = exportedScene.logic.build(props).mount()
                    try {
                        await breakpoint(50)
                    } catch (e) {
                        // if we change the scene while waiting these 50ms, unmount
                        unmount()
                        throw e
                    }
                }
            }
            actions.setScene(sceneId, sceneKey, tabId, params, clickedLink || wasNotLoaded, exportedScene)
        },
        reloadBrowserDueToImportError: () => {
            window.location.reload()
        },
    })),

    // keep this above subscriptions
    afterMount(({ actions, cache, values }) => {
        let initialTabs: SceneTab[] | null = null
        if (!cache.tabsLoaded) {
            const savedSessionTabs = getPersistedSessionTabs() ?? []
            const sessionWithIds = savedSessionTabs.map((tab) => (tab.id ? tab : { ...tab, id: generateTabId() }))
            const savedPinnedTabs = getPersistedPinnedState()
            if (sessionWithIds.length > 0 || savedPinnedTabs) {
                initialTabs = composeTabsFromStorage(savedPinnedTabs, sessionWithIds)
                cache.skipNextPinnedSync = true
                actions.setTabs(initialTabs)
                if (savedPinnedTabs) {
                    cache.skipNextPinnedSync = true
                    actions.setHomepage(savedPinnedTabs.homepage ?? null)
                }

                cache.initialNavigationTabCreated = initialTabs.some((tab) => !tab.pinned)
            }
            cache.tabsLoaded = true
        }
        if (!initialTabs?.length && values.tabs.length === 0) {
            const { currentLocation } = router.values
            actions.setTabs([
                {
                    id: generateTabId(),
                    active: true,
                    pathname: currentLocation.pathname,
                    search: currentLocation.search,
                    hash: currentLocation.hash,
                    title: 'Loading...',
                    iconType: 'loading',
                    pinned: false,
                },
            ])
            cache.initialNavigationTabCreated = true
        }
        actions.loadPinnedTabsFromBackend()
    }),

    urlToAction(({ actions, values, cache }) => {
        const ensureNavigationTabId = (): string => {
            const activeTab = values.activeTab
            const location = router.values.currentLocation
            const hrefString = location ? `${location.pathname}${location.search ?? ''}${location.hash ?? ''}` : ''
            const href = hrefString || undefined

            const createNavigationTab = (): string => {
                const tabId = generateTabId()
                actions.newTab(href, { id: tabId, skipNavigate: true, activate: true })
                cache.initialNavigationTabCreated = true
                return tabId
            }

            if (values.tabs.length === 0) {
                return createNavigationTab()
            }

            if (activeTab?.pinned && !cache.initialNavigationTabCreated) {
                return createNavigationTab()
            }

            if (!activeTab?.id) {
                return createNavigationTab()
            }

            return activeTab.id
        }

        const mapping: Record<
            string,
            (
                params: Params,
                searchParams: Params,
                hashParams: Params,
                payload: {
                    method: string
                }
            ) => any
        > = {}

        for (const path of Object.keys(redirects)) {
            mapping[path] = (params, searchParams, hashParams) => {
                const redirect = redirects[path]
                const redirectUrl =
                    typeof redirect === 'function' ? redirect(params, searchParams, hashParams) : redirect

                router.actions.replace(
                    withForwardedSearchParams(redirectUrl, searchParams, forwardedRedirectQueryParams)
                )
            }
        }
        for (const [path, [scene, sceneKey]] of Object.entries(routes)) {
            mapping[path] = (params, searchParams, hashParams, { method }) => {
                const tabId = ensureNavigationTabId()
                actions.openScene(
                    scene,
                    sceneKey,
                    tabId,
                    {
                        params,
                        searchParams,
                        hashParams,
                    },
                    method
                )
            }
        }

        mapping['/*'] = (_, __, { method }) => {
            const tabId = ensureNavigationTabId()
            return actions.loadScene(Scene.Error404, undefined, tabId, emptySceneParams, method)
        }

        return mapping
    }),

    subscriptions(({ actions, values, cache }) => {
        const schedulePinnedStateSync = (): void => {
            const pinnedTabsForPersistence = getPinnedTabsForPersistence(values.tabs)
            const homepageForPersistence = getHomepageForPersistence(values.homepage)
            const serializedPinnedState = JSON.stringify({
                tabs: pinnedTabsForPersistence,
                homepage: homepageForPersistence,
            })

            if (cache.skipNextPinnedSync) {
                cache.skipNextPinnedSync = false
                cache.lastPersistedPinnedSerialized = serializedPinnedState
                return
            }

            if (cache.lastPersistedPinnedSerialized === serializedPinnedState) {
                return
            }

            cache.lastPersistedPinnedSerialized = serializedPinnedState

            if (cache.persistPinnedTabsTimeout) {
                window.clearTimeout(cache.persistPinnedTabsTimeout)
            }

            cache.persistPinnedTabsTimeout = window.setTimeout(async () => {
                try {
                    await api.update('api/user_pinned_scene_tabs/@me/', {
                        tabs: pinnedTabsForPersistence,
                        homepage: homepageForPersistence,
                    })
                } catch (error) {
                    console.error('Failed to persist pinned scene tabs to backend', error)
                }
            }, 500)
        }

        return {
            titleAndIcon: ({ title, iconType }) => {
                const activeIndex = values.tabs.findIndex((t) => t.active)
                if (activeIndex === -1) {
                    const { currentLocation } = router.values
                    actions.setTabs([
                        {
                            id: generateTabId(),
                            active: true,
                            pathname: currentLocation.pathname,
                            search: currentLocation.search,
                            hash: currentLocation.hash,
                            title: title || 'Loading...',
                            iconType,
                        },
                    ])
                } else {
                    if (!title || title === '...' || title === 'Loading...') {
                        // When the tab is loading, don't flicker between the loaded title and the new one
                        return
                    }
                    const newTabs = values.tabs.map((tab, i) => (i === activeIndex ? { ...tab, title, iconType } : tab))
                    actions.setTabs(newTabs)
                }
                if (!process?.env?.STORYBOOK) {
                    // This persists the changed tab titles in location.history without a replace/push action.
                    // We'll do it outside the action's event loop to avoid race conditions with subscribing.
                    // Somehow it messes up Storybook, so disabled for it.
                    window.setTimeout(() => router.actions.refreshRouterState(), 1)
                }
            },
            tabs: () => {
                cache.initialNavigationTabCreated =
                    cache.initialNavigationTabCreated || values.tabs.some((tab) => !tab.pinned)
                const { tabIds } = values
                for (const id of Object.keys(cache.mountedTabLogic)) {
                    if (!tabIds[id]) {
                        const unmount = cache.mountedTabLogic[id]
                        if (unmount) {
                            try {
                                unmount()
                            } catch (error) {
                                console.error('Error unmounting tab logic:', error)
                            }
                        }
                        delete cache.mountedTabLogic[id]
                        if (cache.lastTrackedSceneByTab) {
                            delete cache.lastTrackedSceneByTab[id]
                        }
                    }
                }
                schedulePinnedStateSync()
            },
            homepage: schedulePinnedStateSync,
        }
    }),
    afterMount(({ cache }) => {
        cache.disposables.add(() => {
            return () => {
                if (cache.persistPinnedTabsTimeout) {
                    window.clearTimeout(cache.persistPinnedTabsTimeout)
                }
            }
        }, 'pinnedTabsBackendPersist')
    }),

    afterMount(({ actions, cache, values }) => {
        cache.disposables.add(() => {
            const onStorage = (event: StorageEvent): void => {
                if (event.key !== getStorageKey(PINNED_TAB_STATE_KEY)) {
                    return
                }
                const storedPinned = getPersistedPinnedState()
                const currentTabs = values.tabs
                const updatedTabs = composeTabsFromStorage(storedPinned, currentTabs)

                const previousActiveTab = currentTabs.find((tab) => tab.active)
                const nextActiveTab = updatedTabs.find((tab) => tab.active)

                cache.skipNextPinnedSync = true
                actions.setTabs(updatedTabs)
                actions.setHomepage(storedPinned?.homepage ?? null)

                if (!nextActiveTab?.pinned) {
                    return
                }

                const location = router.values.currentLocation
                const pathnameChanged = nextActiveTab.pathname !== location?.pathname
                const searchChanged = (nextActiveTab.search ?? '') !== (location?.search ?? '')
                const hashChanged = (nextActiveTab.hash ?? '') !== (location?.hash ?? '')

                // When the active pinned tab changes remotely, make sure the local window navigates too.
                if (previousActiveTab?.id !== nextActiveTab.id || pathnameChanged || searchChanged || hashChanged) {
                    router.actions.push(nextActiveTab.pathname, nextActiveTab.search, nextActiveTab.hash)
                }
            }
            window.addEventListener('storage', onStorage)
            return () => window.removeEventListener('storage', onStorage)
        }, 'pinnedTabsStorageListener')
    }),
    afterMount(({ actions, cache, values }) => {
        cache.disposables.add(() => {
            const onKeyDown = (event: KeyboardEvent): void => {
                if ((event.ctrlKey || event.metaKey) && event.key === 'b') {
                    const element = event.target as HTMLElement
                    if (element?.closest('.NotebookEditor')) {
                        return
                    }

                    event.preventDefault()
                    event.stopPropagation()
                    if (event.shiftKey) {
                        if (values.activeTab) {
                            actions.removeTab(values.activeTab)
                        }
                    } else {
                        actions.newTab()
                    }
                }
            }
            window.addEventListener('keydown', onKeyDown)
            return () => window.removeEventListener('keydown', onKeyDown)
        }, 'keydownListener')
    }),
])
