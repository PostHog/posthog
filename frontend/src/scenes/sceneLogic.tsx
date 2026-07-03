import equal from 'fast-deep-equal'
import { BuiltLogic, actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import api from 'lib/api'
import { TeamMembershipLevel } from 'lib/constants'
import { trackFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { getAppContext } from 'lib/utils/getAppContext'
import { isChunkLoadError } from 'lib/utils/isChunkLoadError'
import { addProjectIdIfMissing, removeProjectIdIfPresent, stripTrailingSlash } from 'lib/utils/kea-router'
import { retryImport } from 'lib/utils/retryImport'
import { identifierToHuman } from 'lib/utils/strings'
import { getRelativeNextPath } from 'lib/utils/url'
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
import { isOnboardingRedirectSuppressed } from './onboarding/legacy/onboardingDelegationState'
import { organizationLogic } from './organizationLogic'
import { preflightLogic } from './PreflightCheck/preflightLogic'
import type { sceneLogicType } from './sceneLogicType'
import { inviteLogic } from './settings/organization/inviteLogic'
import { teamLogic } from './teamLogic'
import { userLogic } from './userLogic'

interface MountedSceneLogic {
    logic: SceneExport['logic']
    logicProps: Record<string, any>
    sceneId: string
    sceneKey?: string
    unmount: () => void
}

const generateTabId = (): string => crypto?.randomUUID?.()?.split('-')?.pop() || `${Date.now()}-${Math.random()}`

/**
 * Homepage snapshot for JSON persistence: strips `sceneParams` (deep/cyclic routing state) and
 * ensures an id. Every other `SceneTab` field is kept so new fields aren't forgotten; if a future
 * field holds non-plain data, omit it here explicitly.
 */
const tabToPersistableSnapshot = (tab: SceneTab): SceneTab => {
    const { sceneParams: _omitSceneParams, ...rest } = tab
    return {
        ...rest,
        id: tab.id || generateTabId(),
    }
}

// Bootstrapped by Django into APP_CONTEXT so the configured homepage is known on first paint,
// before any async fetch — otherwise urlToAction runs with a null homepage and /home can't redirect.
const getBootstrappedHomepage = (): SceneTab | null => {
    const homepage = getAppContext()?.homepage
    return homepage ? tabToPersistableSnapshot(homepage) : null
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
    // /verify_email/<uuid>/<token> — email verification/change confirmation must run its
    // urlToAction (POST /api/users/verify_email/) even when onboarding is incomplete, else
    // /onboarding swallows the click and the email is never updated.
    urls.verifyEmail(),
    '/startups',
    '/coupons',
    '/legal',
]

export function isOnboardingNotRequiredForPath(pathname: string): boolean {
    const path = removeProjectIdIfPresent(pathname)
    return pathPrefixesOnboardingNotRequiredFor.some((prefix) => path.startsWith(prefix))
}

const DelayedLoadingSpinner = (): JSX.Element => {
    const [show, setShow] = useState(false)
    useEffect(() => {
        const timeout = window.setTimeout(() => setShow(true), 500)
        return () => window.clearTimeout(timeout)
    }, [])
    return <>{show ? <Spinner /> : null}</>
}

const scrollMainContentToTop = (): void => {
    const element = document.getElementById('main-content')
    if (!element) {
        return
    }
    window.requestAnimationFrame(() => {
        element.scrollTo({ top: 0 })
    })
}

/**
 * Forwards whitelisted query parameters from the current URL to the redirect URL.
 * Only forwards params that exist in the current URL and don't already exist in the redirect URL.
 * This is specifically used for scene redirects to maintain important query parameters across redirects.
 */
export function withForwardedSearchParams(
    redirectUrl: string,
    currentSearchParams: Params,
    forwardedQueryParams: string[]
): string {
    // If no params to forward, return the original URL
    if (!forwardedQueryParams?.length) {
        return redirectUrl
    }

    const redirectUrlObj = new URL(redirectUrl, window.location.origin)
    const redirectSearchParams = new URLSearchParams(redirectUrlObj.search)
    let paramsWereForwarded = false

    // For each whitelisted param that exists in current URL
    forwardedQueryParams.forEach((param) => {
        if (currentSearchParams[param] !== undefined && !redirectSearchParams.has(param)) {
            redirectSearchParams.set(param, currentSearchParams[param])
            paramsWereForwarded = true
        }
    })

    // Only modify the URL if we actually forwarded any params
    if (!paramsWereForwarded) {
        return redirectUrl
    }

    // Reconstruct the URL with the forwarded params
    redirectUrlObj.search = redirectSearchParams.toString()
    // Return just the pathname and search to avoid origin being included
    return redirectUrlObj.pathname + redirectUrlObj.search + redirectUrlObj.hash
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
        actions: [router, ['locationChanged'], inviteLogic, ['hideInviteModal']],
        values: [billingLogic, ['billing'], organizationLogic, ['organizationBeingDeleted']],
    })),
    afterMount(({ cache }) => {
        cache.mountedSceneLogic = null as MountedSceneLogic | null
        cache.lastTrackedScene = null as { sceneId?: string; sceneKey?: string } | null
    }),
    actions({
        /* 1. Prepares to open the scene, as the listener may override and do something
        else (e.g. redirecting if unauthenticated), then calls (2) `loadScene`*/
        openScene: (sceneId: string, sceneKey: string | undefined, params: SceneParams, method: string) => ({
            sceneId,
            sceneKey,
            params,
            method,
        }),
        // 2. Start loading the scene's Javascript and mount any logic, then calls (3) `setScene`
        loadScene: (sceneId: string, sceneKey: string | undefined, params: SceneParams, method: string) => ({
            sceneId,
            sceneKey,
            params,
            method,
        }),
        // 3. Set the `scene` reducer
        setScene: (
            sceneId: string,
            sceneKey: string | undefined,
            params: SceneParams,
            scrollToTop: boolean = false,
            exportedScene?: SceneExport
        ) => ({
            sceneId,
            sceneKey,
            params,
            scrollToTop,
            exportedScene,
        }),
        setExportedScene: (
            exportedScene: SceneExport,
            sceneId: string,
            sceneKey: string | undefined,
            params: SceneParams
        ) => ({
            exportedScene,
            sceneId,
            sceneKey,
            params,
        }),
        reloadBrowserDueToImportError: true,

        setHomepage: (tab: SceneTab | null) => ({ tab }),
    }),
    reducers({
        sceneId: [
            null as string | null,
            {
                setScene: (_, { sceneId }) => sceneId,
                setExportedScene: (_, { sceneId }) => sceneId,
            },
        ],
        sceneKey: [
            null as string | null,
            {
                setScene: (_, { sceneKey }) => sceneKey ?? null,
                setExportedScene: (_, { sceneKey }) => sceneKey ?? null,
            },
        ],
        sceneParams: [
            emptySceneParams as SceneParams,
            {
                setScene: (_, { params }) => params,
                setExportedScene: (_, { params }) => params,
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
                setScene: (_, { sceneId, sceneKey, params }) => ({
                    sceneId,
                    sceneKey,
                    params,
                }),
            },
        ],
    }),
    // Function form so the bootstrapped default is read at build time (per kea context),
    // not once at module import — production sets APP_CONTEXT before the bundle loads either way.
    reducers(() => ({
        homepage: [
            getBootstrappedHomepage(),
            {
                setHomepage: (_, { tab }) => (tab ? tabToPersistableSnapshot(tab) : null),
            },
        ],
    })),
    selectors({
        sceneConfig: [
            (s) => [s.sceneId],
            (sceneId: Scene): SceneConfig | null => {
                const config = sceneConfigurations[sceneId] || null
                return config
            },
            { resultEqualityCheck: equal },
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
            (s) => [s.activeSceneId, s.activeExportedScene, s.sceneParams],
            (activeSceneId, activeExportedScene, sceneParams): LoadedScene | null => {
                return {
                    ...(activeExportedScene ?? { component: DelayedLoadingSpinner }),
                    id: activeSceneId ?? Scene.Error404,
                    sceneParams: sceneParams,
                }
            },
        ],
        activeSceneComponentParams: [
            (s) => [s.sceneParams],
            (sceneParams): Record<string, any> => {
                return {
                    ...sceneParams.params,
                }
            },
            { resultEqualityCheck: equal },
        ],
        activeSceneLogicProps: [
            (s) => [s.activeExportedScene, s.sceneParams],
            (activeExportedScene, sceneParams): Record<string, any> => {
                return {
                    ...activeExportedScene?.paramsToProps?.(sceneParams),
                }
            },
            { resultEqualityCheck: equal },
        ],
        activeSceneLogic: [
            (s) => [s.activeExportedScene, s.activeSceneLogicProps],
            (activeExportedScene, activeSceneLogicProps): BuiltLogic | null => {
                if (activeExportedScene?.logic) {
                    try {
                        return activeExportedScene.logic.build(activeSceneLogicProps)
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
        activeSceneProductKey: [
            (s) => [s.activeExportedScene],
            (activeExportedScene: SceneExport | null): ProductKey | null => {
                return activeExportedScene?.productKey ?? null
            },
        ],
    }),
    listeners(({ values, actions, cache, props, selectors }) => ({
        setHomepage: ({ tab }) => {
            if (isSharedView()) {
                return
            }
            api.update('api/user_home_settings/@me/', {
                homepage: tab ? tabToPersistableSnapshot(tab) : null,
            }).catch((error) => {
                console.error('Failed to persist homepage', error)
            })
        },
        locationChanged: ({ pathname, search, hash }) => {
            pathname = addProjectIdIfMissing(pathname)

            // Remove trailing slash from the address bar. Route matching itself is handled
            // upstream via `pathFromWindowToRoutes` in initKea.ts so the scene loads even
            // before this replace runs.
            const stripped = stripTrailingSlash(pathname)
            if (stripped !== pathname) {
                router.actions.replace(stripped, search, hash)
            }
        },
        setScene: ({ sceneKey, sceneId, exportedScene, params, scrollToTop }, _, __, previousState) => {
            const {
                sceneId: lastSceneId,
                sceneKey: lastSceneKey,
                params: lastParams,
            } = selectors.lastSetScenePayload(previousState)

            // Do not trigger a new pageview event when only the hashParams change
            if (
                lastSceneId !== sceneId ||
                lastSceneKey !== sceneKey ||
                !equal(lastParams.params, params.params) ||
                JSON.stringify(lastParams.searchParams) !== JSON.stringify(params.searchParams) // `equal` crashes here
            ) {
                const productKey = values.activeSceneProductKey
                posthog.capture('$pageview', productKey ? { product_key: productKey } : undefined)
            }

            const previousScene = selectors.sceneId(previousState)
            if (sceneId !== previousScene) {
                // Clear scene-scoped load-failure toasts so a red banner from the scene we're
                // leaving doesn't linger on top of the new one.
                lemonToast.dismissNavigationScoped()
            }
            if (scrollToTop && sceneId !== previousScene) {
                // Forward navigation (link click) scrolls to top. There is no back/forward scroll
                // restoration: #main-content is an inner scroll container the browser won't restore.
                scrollMainContentToTop()
            }

            let newLogicErrored = false
            if (exportedScene?.logic) {
                try {
                    const builtLogicProps = { ...exportedScene?.paramsToProps?.(params) }
                    const mountedLogic = cache.mountedSceneLogic
                    // Re-applying the same scene should not remount its logic.
                    // Child logics attach to this scene root to keep draft state alive.
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
                                console.error('Error unmounting previous scene logic:', error)
                            }
                        }

                        cache.mountedSceneLogic = {
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
                    posthog.captureException(error, { extra: { sceneId, sceneKey } })
                    newLogicErrored = true
                }
            } else {
                const mountedLogic = cache.mountedSceneLogic
                if (mountedLogic) {
                    try {
                        mountedLogic.unmount()
                    } catch (error) {
                        console.error('Error unmounting previous scene logic:', error)
                    }
                    cache.mountedSceneLogic = null
                }
            }

            if (newLogicErrored) {
                actions.loadScene(Scene.Error404, undefined, emptySceneParams, 'REPLACE')
                return
            }

            const lastTracked = cache.lastTrackedScene
            if (!lastTracked || lastTracked.sceneId !== sceneId || lastTracked.sceneKey !== sceneKey) {
                trackFileSystemLogView({ type: 'scene', ref: sceneId })
                cache.lastTrackedScene = { sceneId, sceneKey }
            }
        },
        openScene: ({ sceneId, sceneKey, params, method }) => {
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
                        !isOnboardingNotRequiredForPath(location.pathname)
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

            actions.loadScene(sceneId, sceneKey, params, method)
        },
        loadScene: async ({ sceneId, sceneKey, params, method }, breakpoint) => {
            const clickedLink = method === 'PUSH'
            if (values.sceneId === sceneId && values.exportedScenes[sceneId]) {
                actions.setScene(sceneId, sceneKey, params, clickedLink, values.exportedScenes[sceneId])
                return
            }

            if (!props.scenes?.[sceneId]) {
                actions.setScene(
                    Scene.Error404,
                    undefined,
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
                const timeout = window.setTimeout(() => actions.setScene(sceneId, sceneKey, params, true), 500)
                let importedScene
                try {
                    window.ESBUILD_LOAD_CHUNKS?.(sceneId)
                    // Capture the importer in the narrowed scope; the early guard above ensures it's
                    // defined, but that narrowing wouldn't flow into the retryImport closure.
                    const importScene = props.scenes[sceneId]
                    importedScene = await retryImport(() => importScene())
                } catch (error: any) {
                    if (isChunkLoadError(error)) {
                        // Reloaded once in the last 20 seconds and now reloading again? Show network error
                        if (
                            values.lastReloadAt &&
                            parseInt(String(values.lastReloadAt)) > new Date().valueOf() - 20000
                        ) {
                            console.error('App assets regenerated. Showing error page.')
                            actions.setScene(Scene.ErrorNetwork, undefined, emptySceneParams, clickedLink)
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
                actions.setExportedScene(exportedScene, sceneId, sceneKey, params)
            }
            actions.setScene(sceneId, sceneKey, params, clickedLink || wasNotLoaded, exportedScene)
        },
        reloadBrowserDueToImportError: () => {
            window.location.reload()
        },
    })),

    urlToAction(({ actions, values }) => {
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
                actions.openScene(
                    scene,
                    sceneKey,
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
            return actions.loadScene(Scene.Error404, undefined, emptySceneParams, method)
        }

        return mapping
    }),
])
