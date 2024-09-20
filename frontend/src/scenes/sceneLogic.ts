import { actions, BuiltLogic, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'
import { commandBarLogic } from 'lib/components/CommandBar/commandBarLogic'
import { BarStatus } from 'lib/components/CommandBar/types'
import { FEATURE_FLAGS, TeamMembershipLevel } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getAppContext } from 'lib/utils/getAppContext'
import { addProjectIdIfMissing, removeProjectIdIfPresent } from 'lib/utils/router-utils'
import posthog from 'posthog-js'
import { emptySceneParams, preloadedScenes, redirects, routes, sceneConfigurations } from 'scenes/scenes'
import { LoadedScene, Params, Scene, SceneConfig, SceneExport, SceneParams } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/types'

import { handleLoginRedirect } from './authentication/loginLogic'
import { billingLogic } from './billing/billingLogic'
import { SOURCE_DETAILS, sourceWizardLogic } from './data-warehouse/new/sourceWizardLogic'
import { onboardingLogic, OnboardingStepKey } from './onboarding/onboardingLogic'
import { organizationLogic } from './organizationLogic'
import { preflightLogic } from './PreflightCheck/preflightLogic'
import type { sceneLogicType } from './sceneLogicType'
import { inviteLogic } from './settings/organization/inviteLogic'
import { teamLogic } from './teamLogic'
import { userLogic } from './userLogic'

export const productUrlMapping: Partial<Record<ProductKey, string[]>> = {
    [ProductKey.SESSION_REPLAY]: [urls.replay()],
    [ProductKey.FEATURE_FLAGS]: [urls.featureFlags(), urls.earlyAccessFeatures(), urls.experiments()],
    [ProductKey.SURVEYS]: [urls.surveys()],
    [ProductKey.PRODUCT_ANALYTICS]: [urls.insights(), urls.webAnalytics()],
    [ProductKey.DATA_WAREHOUSE]: [urls.dataWarehouse()],
}

export const sceneLogic = kea<sceneLogicType>([
    props(
        {} as {
            scenes?: Record<Scene, () => any>
        }
    ),
    path(['scenes', 'sceneLogic']),
    connect(() => ({
        logic: [router, userLogic, preflightLogic],
        actions: [
            router,
            ['locationChanged'],
            commandBarLogic,
            ['setCommandBar'],
            inviteLogic,
            ['hideInviteModal'],
            sourceWizardLogic,
            ['selectConnector', 'handleRedirect', 'setStep'],
        ],
        values: [
            featureFlagLogic,
            ['featureFlags'],
            billingLogic,
            ['billing'],
            organizationLogic,
            ['organizationBeingDeleted'],
        ],
    })),
    actions({
        /* 1. Prepares to open the scene, as the listener may override and do something
        else (e.g. redirecting if unauthenticated), then calls (2) `loadScene`*/
        openScene: (scene: Scene, params: SceneParams, method: string) => ({ scene, params, method }),
        // 2. Start loading the scene's Javascript and mount any logic, then calls (3) `setScene`
        loadScene: (scene: Scene, params: SceneParams, method: string) => ({ scene, params, method }),
        // 3. Set the `scene` reducer
        setScene: (scene: Scene, params: SceneParams, scrollToTop: boolean = false) => ({ scene, params, scrollToTop }),
        setLoadedScene: (loadedScene: LoadedScene) => ({
            loadedScene,
        }),
        reloadBrowserDueToImportError: true,
    }),
    reducers({
        scene: [
            null as Scene | null,
            {
                setScene: (_, payload) => payload.scene,
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
            null as Scene | null,
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
                return isCurrentTeamUnavailable && scene && sceneConfigurations[scene]?.projectBased
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
            (s) => [s.activeLoadedScene, s.sceneParams],
            (activeLoadedScene, sceneParams): BuiltLogic | null =>
                activeLoadedScene?.logic
                    ? activeLoadedScene.logic.build(activeLoadedScene.paramsToProps?.(sceneParams) || {})
                    : null,
        ],
        params: [(s) => [s.sceneParams], (sceneParams): Record<string, string> => sceneParams.params || {}],
        searchParams: [(s) => [s.sceneParams], (sceneParams): Record<string, any> => sceneParams.searchParams || {}],
        hashParams: [(s) => [s.sceneParams], (sceneParams): Record<string, any> => sceneParams.hashParams || {}],
    }),
    listeners(({ values, actions, props, selectors }) => ({
        setScene: ({ scene, scrollToTop }, _, __, previousState) => {
            posthog.capture('$pageview')

            // if we clicked on a link, scroll to top
            const previousScene = selectors.scene(previousState)
            if (scrollToTop && scene !== previousScene) {
                window.scrollTo(0, 0)
            }
        },
        openScene: ({ scene, params, method }) => {
            const sceneConfig = sceneConfigurations[scene] || {}
            const { user } = userLogic.values
            const { preflight } = preflightLogic.values

            if (params.searchParams?.organizationDeleted && !organizationLogic.values.organizationBeingDeleted) {
                lemonToast.success('Organization has been deleted')
                router.actions.push(urls.default())
                return
            }

            if (getAppContext()?.is_region_blocked) {
                // TODO: Later this is where we should redirect to a page to explain the region blocking
            }

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

            // Redirect to the scene's canonical pathname if needed
            const currentPathname = router.values.location.pathname
            const canonicalPathname = addProjectIdIfMissing(router.values.location.pathname)
            if (currentPathname !== canonicalPathname) {
                router.actions.replace(canonicalPathname, router.values.searchParams, router.values.hashParams)
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
                        if (location.pathname !== urls.organizationCreateFirst()) {
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
                        !removeProjectIdIfPresent(location.pathname).startsWith(urls.onboarding('')) &&
                        !removeProjectIdIfPresent(location.pathname).startsWith(urls.products()) &&
                        !removeProjectIdIfPresent(location.pathname).startsWith('/settings') &&
                        !removeProjectIdIfPresent(location.pathname).startsWith(urls.organizationBilling())
                    ) {
                        const allProductUrls = Object.values(productUrlMapping).flat()
                        if (
                            !teamLogic.values.hasOnboardedAnyProduct &&
                            !allProductUrls.some((path) => removeProjectIdIfPresent(location.pathname).startsWith(path))
                        ) {
                            console.warn('No onboarding completed, redirecting to /products')
                            router.actions.replace(urls.products())
                            return
                        }

                        const productKeyFromUrl = Object.keys(productUrlMapping).find((key: string) =>
                            // eslint-disable-next-line @typescript-eslint/no-unnecessary-type-assertion
                            (Object.values(productUrlMapping[key]) as string[]).some(
                                (path: string) =>
                                    removeProjectIdIfPresent(location.pathname).startsWith(path) &&
                                    !path.startsWith('/projects')
                            )
                        )

                        if (
                            productKeyFromUrl &&
                            teamLogic.values.currentTeam &&
                            !teamLogic.values.currentTeam?.has_completed_onboarding_for?.[productKeyFromUrl]
                            // TODO: when removing ff PRODUCT_INTRO_PAGES - should this only happen when in
                            // cloud mode? What is the experience for self-hosted?
                        ) {
                            // TODO: remove after PRODUCT_INTRO_PAGES experiment is complete
                            posthog.capture('should view onboarding product intro', {
                                did_view_intro: values.featureFlags[FEATURE_FLAGS.PRODUCT_INTRO_PAGES] === 'test',
                                product_key: productKeyFromUrl,
                                is_onboarding_first_product: !teamLogic.values.hasOnboardedAnyProduct,
                            })
                            if (
                                values.featureFlags[FEATURE_FLAGS.PRODUCT_INTRO_PAGES] === 'test' ||
                                !teamLogic.values.hasOnboardedAnyProduct
                            ) {
                                console.warn(
                                    `Onboarding not completed for ${productKeyFromUrl}, redirecting to onboarding intro`
                                )
                                onboardingLogic.mount()
                                onboardingLogic.actions.setIncludeIntro(!!values.billing)
                                onboardingLogic.unmount()

                                if (
                                    scene === Scene.DataWarehouseTable &&
                                    params.searchParams.kind == 'hubspot' &&
                                    params.searchParams.code
                                ) {
                                    actions.selectConnector(SOURCE_DETAILS['Hubspot'])
                                    actions.handleRedirect(params.searchParams.kind, {
                                        code: params.searchParams.code,
                                    })
                                    actions.setStep(2)
                                    router.actions.replace(
                                        urls.onboarding(productKeyFromUrl, OnboardingStepKey.LINK_DATA)
                                    )
                                } else {
                                    router.actions.replace(
                                        urls.onboarding(productKeyFromUrl, OnboardingStepKey.PRODUCT_INTRO)
                                    )
                                }
                                return
                            }
                        }
                    }
                }
            }

            actions.loadScene(scene, params, method)
        },
        loadScene: async ({ scene, params, method }, breakpoint) => {
            const clickedLink = method === 'PUSH'
            if (values.scene === scene) {
                actions.setScene(scene, params, clickedLink)
                return
            }

            if (!props.scenes?.[scene]) {
                actions.setScene(Scene.Error404, emptySceneParams, clickedLink)
                return
            }

            let loadedScene = values.loadedScenes[scene]
            const wasNotLoaded = !loadedScene

            if (!loadedScene) {
                // if we can't load the scene in a second, show a spinner
                const timeout = window.setTimeout(() => actions.setScene(scene, params, true), 500)
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
                            actions.setScene(Scene.ErrorNetwork, emptySceneParams, clickedLink)
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
                breakpoint()
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
            actions.setScene(scene, params, clickedLink || wasNotLoaded)
        },
        reloadBrowserDueToImportError: () => {
            window.location.reload()
        },
        locationChanged: () => {
            const {
                location: { pathname, search, hash },
            } = router.values

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
    })),
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
                router.actions.replace(
                    typeof redirect === 'function' ? redirect(params, searchParams, hashParams) : redirect
                )
            }
        }
        for (const [path, scene] of Object.entries(routes)) {
            mapping[path] = (params, searchParams, hashParams, { method }) =>
                actions.openScene(scene, { params, searchParams, hashParams }, method)
        }

        mapping['/*'] = (_, __, { method }) => {
            return actions.loadScene(Scene.Error404, emptySceneParams, method)
        }

        return mapping
    }),
])
