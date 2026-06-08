import equal from 'fast-deep-equal'
import { BuiltLogic, actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { combineUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import api from 'lib/api'
import { TeamMembershipLevel } from 'lib/constants'
import { trackFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { getRelativeNextPath, identifierToHuman } from 'lib/utils'
import { getAppContext } from 'lib/utils/getAppContext'
import { isChunkLoadError } from 'lib/utils/isChunkLoadError'
import { addProjectIdIfMissing, removeProjectIdIfPresent, stripTrailingSlash } from 'lib/utils/router-utils'
import { withForwardedSearchParams } from 'lib/utils/sceneLogicUtils'
import {
    emptySceneParams,
    forwardedRedirectQueryParams,
    preloadedScenes,
    redirects,
    routes,
    sceneConfigurations,
} from 'scenes/scenes'
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
import { urls } from 'scenes/urls'

import { isSharedView } from '~/exporter/exporterViewLogic'
import { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel } from '~/types'

import { handleLoginRedirect } from './authentication/login/loginLogic'
import { billingLogic } from './billing/billingLogic'
import { parseCouponCampaign } from './coupons/utils'
import { isOnboardingRedirectSuppressed } from './onboarding/onboardingDelegationState'
import { organizationLogic } from './organizationLogic'
import { preflightLogic } from './PreflightCheck/preflightLogic'
import type { sceneLogicType } from './sceneLogicType'
import { inviteLogic } from './settings/organization/inviteLogic'
import { teamLogic } from './teamLogic'
import { userLogic } from './userLogic'

interface MountedTabLogic {
    logic: SceneExport['logic']
    logicProps: Record<string, any>
    sceneId: string
    sceneKey?: string
    unmount: () => void
}

const generateTabId = (): string => crypto?.randomUUID?.()?.split('-')?.pop() || `${Date.now()}-${Math.random()}`

/**
 * Snapshot for JSON / structuredClone. Strips only `sceneParams` (deep/cyclic routing state); everything
 * else on `SceneTab` is kept so new fields are not forgotten. If a future field holds non-plain data,
 * omit it here explicitly.
 */
const tabToPersistableSnapshot = (tab: SceneTab, overrides: Partial<SceneTab> = {}): SceneTab => {
    const { sceneParams: _omitSceneParams, ...rest } = tab
    return {
        ...rest,
        id: tab.id || generateTabId(),
        ...overrides,
    }
}

/** Plain tab snapshots for browser history (`structuredClone` in initKea); excludes `sceneParams`. */
export const getTabsSnapshotForHistory = (tabs: SceneTab[]): SceneTab[] => tabs.map((t) => tabToPersistableSnapshot(t))

const sanitizeTabForPersistence = (tab: SceneTab): SceneTab => {
    return tabToPersistableSnapshot(tab, { pinned: true, active: false })
}

// Bootstrapped by Django into APP_CONTEXT so the configured homepage is known on first paint,
// before any async fetch — otherwise urlToAction runs with a null homepage and /home can't redirect.
const getBootstrappedHomepage = (): SceneTab | null => {
    const homepage = getAppContext()?.homepage
    return homepage ? sanitizeTabForPersistence(homepage) : null
}

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

const ensureActiveTab = (tabs: SceneTab[]): SceneTab[] => {
    if (!tabs.some((tab) => tab.active)) {
        if (tabs.length > 0) {
            tabs = tabs.map((tab, index) => ({ ...tab, active: index === 0 }))
        }
    }
    return tabs
}

const pathPrefixesOnboardingNotRequiredFor = [
    urls.onboarding(),
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
    // /integrations/* — OAuth + third-party round-trips: must complete (callback/landing effects)
    // even when onboarding is incomplete, else /onboarding swallows the response. E.g.
    // /integrations/<kind>/callback (urls.integrationsRedirect), stripe confirm-install, vercel link-error.
    '/integrations',
    // /account-connected/<kind> — return after linking GitHub etc.; /complete/github-link/ redirects here.
    '/account-connected',
    // /oauth/authorize and any /oauth/* callback path.
    '/oauth',
    // /connect/vercel/link (urls.vercelConnect) and other connect round-trips.
    '/connect',
    // /agentic/authorize, /agentic/account-mismatch.
    '/agentic',
    // /cli/authorize, /cli/live (CLI auth round-trip).
    '/cli',
    '/startups',
    '/coupons',
]

const DelayedLoadingSpinner = (): JSX.Element => {
    const [show, setShow] = useState(false)
    useEffect(() => {
        const timeout = window.setTimeout(() => setShow(true), 500)
        return () => window.clearTimeout(timeout)
    }, [])
    return <>{show ? <Spinner /> : null}</>
}

const getMainContentElement = (): HTMLElement | null => document.getElementById('main-content')
const restoreMainContentScrollTop = (scrollTop: number, onlyIfTabId?: string): void => {
    const element = getMainContentElement()
    if (!element) {
        return
    }
    if (onlyIfTabId && sceneLogic.findMounted()?.values.activeTabId !== onlyIfTabId) {
        return
    }
    window.requestAnimationFrame(() => {
        element.scrollTo({ top: scrollTop })
    })
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
        actions: [router, ['locationChanged', 'push'], inviteLogic, ['hideInviteModal']],
        values: [billingLogic, ['billing'], organizationLogic, ['organizationBeingDeleted']],
    })),
    afterMount(({ cache }) => {
        cache.mountedTabLogic = {} as Record<string, MountedTabLogic>
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

        newTab: (href?: string | null, options?: { activate?: boolean; skipNavigate?: boolean; id?: string }) => {
            const tabId = options?.id ?? generateTabId()
            return {
                href,
                options,
                tabId,
            }
        },
        setTabs: (tabs: SceneTab[]) => ({ tabs }),
        applyTitleAndIcon: (title: string, iconType: FileSystemIconType | 'loading' | 'blank') => ({
            title,
            iconType,
        }),
        setHomepage: (tab: SceneTab | null) => ({ tab }),
        setTabScrollDepth: (tabId: string, scrollTop: number) => ({ tabId, scrollTop }),
    }),
    reducers({
        // We store all state in "tabs". This allows us to have multiple tabs open, each with its own scene and parameters.
        tabs: [
            [] as SceneTab[],
            {
                setTabs: (_, { tabs }) => ensureActiveTab(sortTabsPinnedFirst(tabs)),
                newTab: (state, { href, options, tabId }) => {
                    const activate = options?.activate ?? true
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
                        title: 'Search',
                        iconType: 'search',
                        pinned: false,
                    }
                    return sortTabsPinnedFirst([...baseTabs, newTab])
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
                setScene: (_, { sceneId, sceneKey, tabId, params }) => ({
                    sceneId,
                    sceneKey,
                    tabId,
                    params,
                }),
            },
        ],
        tabScrollDepths: [
            {} as Record<string, number>,
            {
                setTabScrollDepth: (state, { tabId, scrollTop }) => ({
                    ...state,
                    [tabId]: scrollTop,
                }),
                setTabs: (state, { tabs }) => {
                    // remove those no longer present
                    return tabs.reduce(
                        (acc, tab) => {
                            if (state[tab.id] !== undefined) {
                                acc[tab.id] = state[tab.id]
                            }
                            return acc
                        },
                        {} as Record<string, number>
                    )
                },
            },
        ],
    }),
    // Function form so the bootstrapped default is read at build time (per kea context),
    // not once at module import — production sets APP_CONTEXT before the bundle loads either way.
    reducers(() => ({
        homepage: [
            getBootstrappedHomepage(),
            {
                setHomepage: (_, { tab }) => (tab ? sanitizeTabForPersistence(tab) : null),
            },
        ],
    })),
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
                    !location.pathname.startsWith('/settings')
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
                    try {
                        return activeExportedScene.logic.build(activeSceneLogicPropsWithTabId)
                    } catch (e) {
                        // Building a keyed logic with undefined key (e.g. during a scene
                        // transition before paramsToProps has resolved) throws
                        // "Undefined key for logic". Swallow only that case so the scene
                        // doesn't hard-crash; the next render with resolved params will
                        // rebuild. Re-throw anything else so genuine build bugs (wrong
                        // prop shape, missing reducer, etc.) still surface loudly.
                        if (e instanceof Error && e.message.includes('Undefined key for logic')) {
                            posthog.captureException(e, { source: 'sceneLogic.activeSceneLogic' })
                            return null
                        }
                        throw e
                    }
                }

                return null
            },
        ],
        searchParams: [(s) => [s.sceneParams], (sceneParams): Record<string, any> => sceneParams.searchParams || {}],
        hashParams: [(s) => [s.sceneParams], (sceneParams): Record<string, any> => sceneParams.hashParams || {}],

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
        firstTabIsActive: [
            (s) => [s.activeTabId, s.tabs],
            (activeTabId, tabs): boolean => {
                return activeTabId === tabs[0]?.id
            },
        ],
        activeSceneProductKey: [
            (s) => [s.activeExportedScene],
            (activeExportedScene: SceneExport | null): ProductKey | null => {
                return activeExportedScene?.productKey ?? null
            },
        ],
    }),
    listeners(({ values, actions, cache, props, selectors }) => ({
        applyTitleAndIcon: ({ title, iconType }) => {
            if (!title || title === '...' || title === 'Loading...') {
                // When the tab is loading, don't flicker between the loaded title and the new one
                return
            }
            const activeIndex = values.tabs.findIndex((t) => t.active)
            if (activeIndex !== -1) {
                actions.setTabs(
                    values.tabs.map((tab, i) => (i === activeIndex ? { ...tab, title, iconType, badge: false } : tab))
                )
            }
            if (!process?.env?.STORYBOOK) {
                // Persists the changed tab titles in location.history without a replace/push action.
                // Outside the action's event loop to avoid race conditions with subscribing.
                // Somehow it messes up Storybook, so disabled for it.
                window.setTimeout(() => router.actions.refreshRouterState(), 1)
            }
        },
        newTab: ({ href, options }) => {
            if (!(options?.skipNavigate ?? false)) {
                router.actions.push(href || urls.newTab())
            }
        },
        setHomepage: ({ tab }) => {
            if (isSharedView()) {
                return
            }
            api.update('api/user_home_settings/@me/', {
                homepage: tab ? sanitizeTabForPersistence(tab) : null,
            }).catch((error) => {
                console.error('Failed to persist homepage', error)
            })
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

            // Remove trailing slash from the address bar. Route matching itself is handled
            // upstream via `pathFromWindowToRoutes` in initKea.ts so the scene loads even
            // before this replace runs.
            const stripped = stripTrailingSlash(pathname)
            if (stripped !== pathname) {
                router.actions.replace(stripped, search, hash)
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
                const productKey = values.activeSceneProductKey
                posthog.capture('$pageview', productKey ? { product_key: productKey } : undefined)
            }

            if (tabId !== lastTabId) {
                const scrollTop = values.tabScrollDepths[tabId] ?? 0
                window.setTimeout(() => restoreMainContentScrollTop(scrollTop, tabId), 1)
                window.setTimeout(() => restoreMainContentScrollTop(scrollTop, tabId), 10)
                window.setTimeout(() => restoreMainContentScrollTop(scrollTop, tabId), 100)
                window.setTimeout(() => restoreMainContentScrollTop(scrollTop, tabId), 300)
            } else {
                // if we clicked on a link, scroll to top
                const previousScene = selectors.sceneId(previousState)
                if (scrollToTop && sceneId !== previousScene) {
                    restoreMainContentScrollTop(0)
                }
            }

            let newLogicErrored = false
            if (exportedScene?.logic) {
                try {
                    const builtLogicProps = { tabId, ...exportedScene?.paramsToProps?.(params) }
                    const mountedLogic = cache.mountedTabLogic[tabId]
                    // Re-activating an existing internal tab should not remount its scene logic.
                    // Child logics attach to this scene root to keep draft state alive while inactive.
                    const canKeepMountedLogic =
                        mountedLogic?.logic === exportedScene.logic &&
                        mountedLogic?.sceneId === sceneId &&
                        mountedLogic.sceneKey === sceneKey &&
                        equal(mountedLogic.logicProps, builtLogicProps)

                    if (!canKeepMountedLogic) {
                        const builtLogic = exportedScene.logic(builtLogicProps)

                        if (mountedLogic) {
                            try {
                                mountedLogic.unmount()
                            } catch (error) {
                                console.error('Error unmounting previous tab logic:', error)
                            }
                            delete cache.mountedTabLogic[tabId]
                        }

                        cache.mountedTabLogic[tabId] = {
                            logic: exportedScene.logic,
                            logicProps: builtLogicProps,
                            sceneId,
                            sceneKey,
                            unmount: builtLogic.mount(),
                        }
                    }
                } catch (error) {
                    // Scene logic builders (e.g. dashboardLogic.key()) can throw on malformed
                    // route params like `/dashboard/abc`. Capture so regressions surface, then
                    // route to Error404 so the user sees a proper 404 instead of a blank crash.
                    posthog.captureException(error, { extra: { sceneId, sceneKey, tabId } })
                    newLogicErrored = true
                }
            } else {
                const mountedLogic = cache.mountedTabLogic[tabId]
                if (mountedLogic) {
                    try {
                        mountedLogic.unmount()
                    } catch (error) {
                        console.error('Error unmounting previous tab logic:', error)
                    }
                    delete cache.mountedTabLogic[tabId]
                }
            }

            if (newLogicErrored) {
                actions.loadScene(Scene.Error404, undefined, tabId, emptySceneParams, 'REPLACE')
                return
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
                router.actions.replace(urls.projectRoot())
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

                if (sceneId !== Scene.InviteSignup) {
                    // Redirect to org/project creation if there's no org/project respectively, unless using invite
                    if (organizationLogic.values.isCurrentOrganizationUnavailable) {
                        if (
                            location.pathname !== urls.organizationCreateFirst() &&
                            !location.pathname.startsWith(urls.settings('user'))
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
                        // Or redirect to onboarding in case we detect people have to do onboarding for their first project
                        user.organization?.teams.length === 1 &&
                        teamLogic.values.currentTeam &&
                        !teamLogic.values.currentTeam.is_demo &&
                        !teamLogic.values.hasOnboardedAnyProduct &&
                        !teamLogic.values.currentTeam?.ingested_event &&
                        // Suppress the redirect when the user has explicitly exited onboarding
                        // (skipped for later, or delegated to a teammate with a pending invite).
                        // If the delegation invite is cancelled or expires, the backend clears
                        // onboarding_delegated_to_invite and the redirect re-fires.
                        !isOnboardingRedirectSuppressed(user) &&
                        !pathPrefixesOnboardingNotRequiredFor.some((path) =>
                            removeProjectIdIfPresent(location.pathname).startsWith(path)
                        )
                    ) {
                        const nextUrl =
                            getRelativeNextPath(params.searchParams.next, location) ??
                            removeProjectIdIfPresent(location.pathname)

                        // Check if user is coming from a coupon campaign link
                        const campaign = nextUrl ? parseCouponCampaign(nextUrl) : null
                        if (campaign) {
                            router.actions.replace(urls.onboarding({ campaign }), { next: nextUrl })
                            return
                        }

                        router.actions.replace(urls.onboarding(), nextUrl ? { next: nextUrl } : undefined)
                        return
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
                    if (isChunkLoadError(error)) {
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
            }
            actions.setScene(sceneId, sceneKey, tabId, params, clickedLink || wasNotLoaded, exportedScene)
        },
        reloadBrowserDueToImportError: () => {
            window.location.reload()
        },
    })),

    // keep this above subscriptions
    afterMount(({ actions, cache, values }) => {
        // PostHog tabs were removed. Always start with a single fresh tab —
        // persisted tabs are surfaced once in the farewell modal and then cleared.
        cache.tabsLoaded = true
        if (values.tabs.length === 0) {
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
        // The Home button (via `/`) and a direct visit to /home should both land on the user's
        // configured homepage (set in the Configure home modal). Redirect there unless we're
        // already at it, which also guards against loops when the homepage is the launchpad itself.
        const redirectToConfiguredHomepage = (searchParams: Params): boolean => {
            const homepage = values.homepage
            if (!homepage) {
                return false
            }
            let targetPathname = addProjectIdIfMissing(homepage.pathname || urls.projectHomepage())
            if (removeProjectIdIfPresent(targetPathname) === '/') {
                targetPathname = addProjectIdIfMissing(urls.projectHomepage())
            }
            // Forward allow-listed params (e.g. modal) onto the homepage the same way the launchpad
            // redirect does, and compare against that final target so a forwarded param can't loop.
            const target = withForwardedSearchParams(
                targetPathname + (homepage.search || '') + (homepage.hash || ''),
                searchParams,
                forwardedRedirectQueryParams
            )
            const loc = router.values.currentLocation
            if (addProjectIdIfMissing(loc.pathname) + (loc.search || '') + (loc.hash || '') === target) {
                return false
            }
            router.actions.replace(target)
            return true
        }

        mapping['/'] = (_params, searchParams) => {
            if (redirectToConfiguredHomepage(searchParams)) {
                return
            }
            router.actions.replace(
                withForwardedSearchParams(urls.projectHomepage(), searchParams, forwardedRedirectQueryParams)
            )
        }

        const projectHomepagePath = urls.projectHomepage()
        for (const [path, [scene, sceneKey]] of Object.entries(routes)) {
            mapping[path] = (params, searchParams, hashParams, { method }) => {
                // A direct visit to /home honors the configured homepage just like the Home button.
                if (path === projectHomepagePath && redirectToConfiguredHomepage(searchParams)) {
                    return
                }
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
                    if (!process?.env?.STORYBOOK) {
                        window.setTimeout(() => router.actions.refreshRouterState(), 1)
                    }
                } else {
                    if (typeof document !== 'undefined' && document.visibilityState !== 'visible') {
                        cache.pendingTitleAndIcon = { title, iconType }
                        return
                    }
                    cache.pendingTitleAndIcon = null
                    actions.applyTitleAndIcon(title, iconType)
                }
            },
            tabs: () => {
                cache.initialNavigationTabCreated =
                    cache.initialNavigationTabCreated || values.tabs.some((tab) => !tab.pinned)
                const { tabIds } = values
                for (const id of Object.keys(cache.mountedTabLogic)) {
                    if (!tabIds[id]) {
                        const mountedLogic = cache.mountedTabLogic[id]
                        if (mountedLogic) {
                            try {
                                mountedLogic.unmount()
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
            },
        }
    }),

    afterMount(({ actions, cache }) => {
        cache.disposables.add(
            () => {
                const onVisibilityChange = (): void => {
                    if (document.visibilityState === 'visible' && cache.pendingTitleAndIcon) {
                        const { title, iconType } = cache.pendingTitleAndIcon
                        cache.pendingTitleAndIcon = null
                        actions.applyTitleAndIcon(title, iconType)
                    }
                }
                document.addEventListener('visibilitychange', onVisibilityChange)
                return () => document.removeEventListener('visibilitychange', onVisibilityChange)
            },
            'titleAndIconVisibilitySync',
            { pauseOnPageHidden: false }
        )
    }),
])
