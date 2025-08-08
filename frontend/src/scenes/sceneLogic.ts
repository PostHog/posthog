import { actions, afterMount, BuiltLogic, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { combineUrl, router, urlToAction } from 'kea-router'
import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { BarStatus } from 'lib/components/CommandBar/types'
import { TeamMembershipLevel } from 'lib/constants'
import { identifierToHuman, getRelativeNextPath } from 'lib/utils'
import { addProjectIdIfMissing, removeProjectIdIfPresent } from 'lib/utils/router-utils'
import { withForwardedSearchParams } from 'lib/utils/sceneLogicUtils'
import posthog from 'posthog-js'
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
    sceneToAccessControlResourceType,
} from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { AccessControlLevel, PipelineTab, ProductKey, OnboardingStepKey } from '~/types'

import { handleLoginRedirect } from './authentication/loginLogic'
import { billingLogic } from './billing/billingLogic'
import { organizationLogic } from './organizationLogic'
import { preflightLogic } from './PreflightCheck/preflightLogic'
import type { sceneLogicType } from './sceneLogicType'
import { inviteLogic } from './settings/organization/inviteLogic'
import { teamLogic } from './teamLogic'
import { userLogic } from './userLogic'
import { arrayMove } from '@dnd-kit/sortable'
import { subscriptions } from 'kea-subscriptions'

export interface SceneTab {
    id: string
    pathname: string
    search: string
    hash: string
    title: string
    active: boolean
}

const TAB_STATE_KEY = 'scene-tabs-state'
const persistTabs = (tabs: SceneTab[]): void => {
    sessionStorage.setItem(TAB_STATE_KEY, JSON.stringify(tabs))
}
const getPersistedTabs: () => SceneTab[] | null = () => {
    const savedTabs = sessionStorage.getItem(TAB_STATE_KEY)
    if (savedTabs) {
        try {
            return JSON.parse(savedTabs)
        } catch (e) {
            console.error('Failed to parse saved tabs from sessionStorage:', e)
        }
    }
    return null
}
const generateTabId = (): string => crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`

export const productUrlMapping: Partial<Record<ProductKey, string[]>> = {
    [ProductKey.SESSION_REPLAY]: [urls.replay()],
    [ProductKey.FEATURE_FLAGS]: [urls.featureFlags(), urls.earlyAccessFeatures(), urls.experiments()],
    [ProductKey.SURVEYS]: [urls.surveys()],
    [ProductKey.PRODUCT_ANALYTICS]: [urls.insights()],
    [ProductKey.DATA_WAREHOUSE]: [urls.sqlEditor(), urls.pipeline(PipelineTab.Sources)],
    [ProductKey.WEB_ANALYTICS]: [urls.webAnalytics()],
    [ProductKey.ERROR_TRACKING]: [urls.errorTracking()],
}

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
        values: [billingLogic, ['billing'], organizationLogic, ['organizationBeingDeleted']],
    })),
    afterMount(({ cache }) => {
        cache.mountedTabLogic = {} as Record<string, () => void>
    }),
    actions({
        /* 1. Prepares to open the scene, as the listener may override and do something
        else (e.g. redirecting if unauthenticated), then calls (2) `loadScene`*/
        openScene: (scene: string, sceneKey: string | null, params: SceneParams, method: string) => ({
            scene,
            sceneKey,
            params,
            method,
        }),
        // 2. Start loading the scene's Javascript and mount any logic, then calls (3) `setScene`
        loadScene: (scene: string, sceneKey: string | null, params: SceneParams, method: string) => ({
            scene,
            sceneKey,
            params,
            method,
        }),
        // 3. Set the `scene` reducer
        setScene: (
            scene: string,
            sceneKey: string | null,
            params: SceneParams,
            scrollToTop: boolean = false,
            loadedScene?: LoadedScene
        ) => ({
            scene,
            sceneKey,
            params,
            scrollToTop,
            loadedScene,
        }),
        setLoadedScene: (loadedScene: LoadedScene) => ({
            loadedScene,
        }),
        reloadBrowserDueToImportError: true,

        newTab: true,
        setTabs: (tabs: SceneTab[]) => ({ tabs }),
        removeTab: (tab: SceneTab) => ({ tab }),
        activateTab: (tab: SceneTab) => ({ tab }),
        clickOnTab: (tab: SceneTab) => ({ tab }),
        reorderTabs: (activeId: string, overId: string) => ({ activeId, overId }),
    }),
    reducers({
        scene: [
            null as string | null,
            {
                setScene: (_, payload) => payload.scene,
            },
        ],
        sceneKey: [
            null as string | null,
            {
                setScene: (_, payload) => payload.sceneKey,
            },
        ],
        loadedScenes: [
            preloadedScenes,
            {
                setScene: (state, { scene, params }) =>
                    scene in state
                        ? {
                              ...state,
                              [scene]: { ...state[scene], sceneParams: params, lastTouch: new Date().valueOf() },
                          }
                        : state,
                setLoadedScene: (state, { loadedScene }) => ({
                    ...state,
                    [loadedScene.id]: { ...loadedScene, lastTouch: new Date().valueOf() },
                }),
            },
        ],
        loadingScene: [
            null as string | null,
            {
                loadScene: (_, { scene }) => scene,
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
        tabs: [
            [] as SceneTab[],
            {
                setTabs: (_, { tabs }) => tabs,
                newTab: (state) => {
                    return [
                        ...state.map((tab) => (tab.active ? { ...tab, active: false } : tab)),
                        {
                            id: generateTabId(),
                            active: true,
                            pathname: addProjectIdIfMissing('/new'),
                            search: '',
                            hash: '',
                            title: 'New tab',
                        },
                    ]
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
                    return newState
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
                    return newState
                },
                reorderTabs: (state, { activeId, overId }) => {
                    const oldIndex = state.findIndex((t) => t.id === activeId)
                    const newIndex = state.findIndex((t) => t.id === overId)
                    if (oldIndex === -1 || newIndex === -1 || oldIndex === newIndex) {
                        return state
                    }
                    return arrayMove(state, oldIndex, newIndex)
                },
            },
        ],
    }),
    selectors({
        sceneConfig: [
            (s) => [s.scene],
            (scene: Scene): SceneConfig | null => {
                return sceneConfigurations[scene] || null
            },
        ],
        activeScene: [
            (s) => [s.scene, teamLogic.selectors.isCurrentTeamUnavailable],
            (scene, isCurrentTeamUnavailable) => {
                const effectiveResourceAccessControl = window.POSTHOG_APP_CONTEXT?.effective_resource_access_control

                // Get the access control resource type for the current scene
                const sceneAccessControlResource = scene ? sceneToAccessControlResourceType[scene as Scene] : null

                // Check if the user has effective access to this resource (includes specific object access)
                if (
                    sceneAccessControlResource &&
                    effectiveResourceAccessControl &&
                    effectiveResourceAccessControl[sceneAccessControlResource] === AccessControlLevel.None
                ) {
                    return Scene.ErrorAccessDenied
                }

                return isCurrentTeamUnavailable &&
                    scene &&
                    sceneConfigurations[scene]?.projectBased &&
                    location.pathname !== urls.settings('user-danger-zone')
                    ? Scene.ErrorProjectUnavailable
                    : scene
            },
        ],
        activeLoadedScene: [
            (s) => [s.activeScene, s.loadedScenes],
            (activeScene, loadedScenes) => (activeScene ? loadedScenes[activeScene] : null),
        ],
        sceneParams: [
            (s) => [s.activeLoadedScene],
            (activeLoadedScene): SceneParams =>
                activeLoadedScene?.sceneParams || { params: {}, searchParams: {}, hashParams: {} },
        ],
        activeSceneLogic: [
            (s) => [s.activeLoadedScene, s.sceneParams, s.activeTabId],
            (activeLoadedScene, sceneParams, activeTabId): BuiltLogic | null => {
                return activeLoadedScene?.logic
                    ? activeLoadedScene.logic.build({
                          ...activeLoadedScene.paramsToProps?.(sceneParams),
                          tabId: activeTabId,
                      })
                    : null
            },
        ],
        params: [(s) => [s.sceneParams], (sceneParams): Record<string, string> => sceneParams.params || {}],
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
        activeTab: [
            (s) => [s.tabs],
            (tabs: SceneTab[]): SceneTab | null => {
                return tabs.find((tab) => tab.active) || null
            },
        ],
        activeTabId: [
            (s) => [s.activeTab],
            (activeTab: SceneTab | null): string | null => {
                return activeTab ? activeTab.id : null
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
        title: [
            (s) => [
                // We're effectively passing the selector through to the scene logic, and "recalculating"
                // this every time it's rendered. Caching will happen within the scene's breadcrumb selector.
                (state, props): string => {
                    const activeSceneLogic = sceneLogic.selectors.activeSceneLogic(state, props)
                    if (activeSceneLogic && 'breadcrumbs' in activeSceneLogic.selectors) {
                        try {
                            const activeLoadedScene = sceneLogic.selectors.activeLoadedScene(state, props)
                            const bc = activeSceneLogic.selectors.breadcrumbs(
                                state,
                                activeLoadedScene?.paramsToProps?.(activeLoadedScene?.sceneParams) || props
                            )
                            return bc.length > 0 ? bc[bc.length - 1].name : '...'
                        } catch {
                            // If the breadcrumb selector fails, we'll just ignore it and return a placeholder value below
                        }
                    }

                    const activeScene = s.activeScene(state, props)
                    if (activeScene) {
                        const sceneConfig = s.sceneConfig(state, props)
                        return sceneConfig?.name ?? identifierToHuman(activeScene)
                    }
                    return '...'
                },
            ],
            (title): string => title,
        ],
    }),
    listeners(({ values, actions, cache, props, selectors }) => ({
        newTab: () => {
            persistTabs(values.tabs)
            router.actions.push(urls.newTab())
        },
        setTabs: () => persistTabs(values.tabs),
        activateTab: () => persistTabs(values.tabs),
        removeTab: ({ tab }) => {
            if (tab.active) {
                // values.activeTab will already be the new active tab from the reducer
                const { activeTab } = values
                if (activeTab) {
                    router.actions.push(activeTab.pathname, activeTab.search, activeTab.hash)
                } else {
                    persistTabs(values.tabs)
                }
            } else {
                persistTabs(values.tabs)
            }
        },
        clickOnTab: ({ tab }) => {
            if (!tab.active) {
                actions.activateTab(tab)
            }
            router.actions.push(tab.pathname, tab.search, tab.hash)
            persistTabs(values.tabs)
        },
        reorderTabs: () => {
            persistTabs(values.tabs)
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
                    { id: generateTabId(), active: true, pathname, search, hash, title: 'Loading...' },
                ])
            }
            persistTabs(values.tabs)
        },
        locationChanged: ({ pathname, search, hash, routerState, method }) => {
            pathname = addProjectIdIfMissing(pathname)
            if (routerState?.tabs && method !== 'PUSH') {
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
                    { id: generateTabId(), active: true, pathname, search, hash, title: 'Loading...' },
                ])
            }
            persistTabs(values.tabs)

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
        setScene: ({ scene, loadedScene, params, scrollToTop }, _, __, previousState) => {
            posthog.capture('$pageview')

            // if we clicked on a link, scroll to top
            const previousScene = selectors.scene(previousState)
            if (scrollToTop && scene !== previousScene) {
                window.scrollTo(0, 0)
            }

            const activeTabId = values.activeTabId
            if (!activeTabId) {
                console.warn('No active tab found when setting scene logic')
                return
            }
            const unmount = cache.mountedTabLogic[activeTabId]
            if (unmount) {
                window.setTimeout(unmount, 50)
                delete cache.mountedTabLogic[activeTabId]
            }
            if (loadedScene?.logic) {
                cache.mountedTabLogic[activeTabId] = loadedScene?.logic(loadedScene?.paramsToProps?.(params)).mount()
            }
        },
        openScene: ({ scene, sceneKey, params, method }) => {
            const sceneConfig = sceneConfigurations[scene] || {}
            const { user } = userLogic.values
            const { preflight } = preflightLogic.values

            if (scene === Scene.Signup && preflight && !preflight.can_create_org) {
                // If user is on an already initiated self-hosted instance, redirect away from signup
                router.actions.replace(urls.login())
                return
            }
            if (scene === Scene.Login && preflight?.demo) {
                // In the demo environment, there's only passwordless "login" via the signup scene
                router.actions.replace(urls.signup())
                return
            }
            if (scene === Scene.MoveToPostHogCloud && preflight?.cloud) {
                router.actions.replace(urls.projectHomepage())
                return
            }

            if (user) {
                // If user is already logged in, redirect away from unauthenticated-only routes (e.g. /signup)
                if (sceneConfig.onlyUnauthenticated) {
                    if (scene === Scene.Login) {
                        handleLoginRedirect()
                    } else {
                        router.actions.replace(urls.default())
                    }
                    return
                }

                // Redirect to org/project creation if there's no org/project respectively, unless using invite
                if (scene !== Scene.InviteSignup) {
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
                            if (location.pathname !== urls.projectCreateFirst()) {
                                console.warn(
                                    'Project not available and no other projects, redirecting to project creation'
                                )
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

                        const productKeyFromUrl = Object.keys(productUrlMapping).find((key) =>
                            productUrlMapping[key as ProductKey]?.some(
                                (path: string) =>
                                    removeProjectIdIfPresent(location.pathname).startsWith(path) &&
                                    !path.startsWith('/projects')
                            )
                        )

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

                                router.actions.replace(urls.onboarding(productKeyFromUrl, OnboardingStepKey.INSTALL))
                                return
                            }
                        }
                    }
                }
            }

            actions.loadScene(scene, sceneKey, params, method)
        },
        loadScene: async ({ scene, sceneKey, params, method }, breakpoint) => {
            const clickedLink = method === 'PUSH'
            if (values.scene === scene) {
                actions.setScene(scene, sceneKey, params, clickedLink, values.loadedScenes[scene])
                return
            }

            if (!props.scenes?.[scene]) {
                actions.setScene(Scene.Error404, null, emptySceneParams, clickedLink, values.loadedScenes[scene])
                return
            }

            let loadedScene = values.loadedScenes[scene]
            const wasNotLoaded = !loadedScene

            if (!loadedScene) {
                // if we can't load the scene in a second, show a spinner
                const timeout = window.setTimeout(() => actions.setScene(scene, sceneKey, params, true), 500)
                let importedScene
                try {
                    window.ESBUILD_LOAD_CHUNKS?.(scene)
                    importedScene = await props.scenes[scene]()
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
                            actions.setScene(Scene.ErrorNetwork, null, emptySceneParams, clickedLink)
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
                if (values.scene !== scene) {
                    breakpoint()
                }
                const { default: defaultExport, logic, scene: _scene, ...others } = importedScene

                if (_scene) {
                    loadedScene = { id: scene, ...(_scene as SceneExport), sceneParams: params }
                } else if (defaultExport) {
                    console.warn(`Scene ${scene} not yet converted to use SceneExport!`)
                    loadedScene = {
                        id: scene,
                        component: defaultExport,
                        logic: logic,
                        sceneParams: params,
                    }
                } else {
                    console.warn(`Scene ${scene} not yet converted to use SceneExport!`)
                    loadedScene = {
                        id: scene,
                        component:
                            Object.keys(others).length === 1
                                ? others[Object.keys(others)[0]]
                                : values.loadedScenes[Scene.Error404].component,
                        logic: logic,
                        sceneParams: params,
                    }
                    if (Object.keys(others).length > 1) {
                        console.error('There are multiple exports for this scene. Showing 404 instead.')
                    }
                }
                actions.setLoadedScene(loadedScene)

                if (loadedScene.logic) {
                    // initialize the logic and give it 50ms to load before opening the scene
                    const unmount = loadedScene.logic.build(loadedScene.paramsToProps?.(params) || {}).mount()
                    try {
                        await breakpoint(50)
                    } catch (e) {
                        // if we change the scene while waiting these 50ms, unmount
                        unmount()
                        throw e
                    }
                }
            }
            actions.setScene(scene, sceneKey, params, clickedLink || wasNotLoaded, loadedScene)
        },
        reloadBrowserDueToImportError: () => {
            window.location.reload()
        },
    })),

    // keep this above subscriptions
    afterMount(({ actions, cache, values }) => {
        if (!cache.tabsLoaded) {
            const savedTabs = getPersistedTabs()
            const withIds = savedTabs?.map((t) => (t.id ? t : { ...t, id: generateTabId() }))
            if (withIds) {
                actions.setTabs(withIds)
            }
            cache.tabsLoaded = true
        }
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
                },
            ])
        }
    }),

    urlToAction(({ actions }) => {
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
            mapping[path] = (params, searchParams, hashParams, { method }) =>
                actions.openScene(scene, sceneKey, { params, searchParams, hashParams }, method)
        }

        mapping['/*'] = (_, __, { method }) => {
            return actions.loadScene(Scene.Error404, null, emptySceneParams, method)
        }

        return mapping
    }),

    subscriptions(({ actions, values, cache }) => ({
        title: (title) => {
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
                    },
                ])
            } else {
                if (!title || title === '...' || title === 'Loading...') {
                    // When the tab is loading, don't flicker between the loaded title and the new one
                    return
                }
                const newTabs = values.tabs.map((tab, i) => (i === activeIndex ? { ...tab, title } : tab))
                actions.setTabs(newTabs)
            }
            // When the title changes, trigger a history REPLACE event to persist the new title in the browser
            const { currentLocation } = router.values
            router.actions.replace(currentLocation.pathname, currentLocation.search, currentLocation.hash)
        },
        tabs: () => {
            const { tabIds } = values
            for (const id of Object.keys(cache.mountedTabLogic)) {
                if (!tabIds[id]) {
                    const mountedTabLogic = cache.mountedTabLogic[id]
                    if (mountedTabLogic) {
                        try {
                            mountedTabLogic.unmount()
                        } catch (error) {
                            console.error('Error unmounting tab logic:', error)
                        }
                    }
                    delete cache.mountedTabLogic[id]
                }
            }
        },
    })),
])
