import { BuiltLogic, kea, props, path, connect, actions, reducers, selectors, listeners } from 'kea'
import { router, urlToAction } from 'kea-router'
import posthog from 'posthog-js'
import type { sceneLogicType } from './sceneLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from './PreflightCheck/preflightLogic'
import { AvailableFeature } from '~/types'
import { userLogic } from './userLogic'
import { handleLoginRedirect } from './authentication/loginLogic'
import { teamLogic } from './teamLogic'
import { urls } from 'scenes/urls'
import { LoadedScene, Params, Scene, SceneConfig, SceneExport, SceneParams } from 'scenes/sceneTypes'
import { emptySceneParams, preloadedScenes, redirects, routes, sceneConfigurations } from 'scenes/scenes'
import { organizationLogic } from './organizationLogic'
import { appContextLogic } from './appContextLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

/** Mapping of some scenes that aren't directly accessible from the sidebar to ones that are - for the sidebar. */
const sceneNavAlias: Partial<Record<Scene, Scene>> = {
    [Scene.Action]: Scene.DataManagement,
    [Scene.Actions]: Scene.DataManagement,
    [Scene.EventDefinitions]: Scene.DataManagement,
    [Scene.PropertyDefinitions]: Scene.DataManagement,
    [Scene.EventDefinition]: Scene.DataManagement,
    [Scene.PropertyDefinition]: Scene.DataManagement,
    [Scene.IngestionWarnings]: Scene.DataManagement,
    [Scene.Person]: Scene.Persons,
    [Scene.Cohort]: Scene.Cohorts,
    [Scene.Groups]: Scene.Persons,
    [Scene.Experiment]: Scene.Experiments,
    [Scene.Group]: Scene.Persons,
    [Scene.Dashboard]: Scene.Dashboards,
    [Scene.FeatureFlag]: Scene.FeatureFlags,
    [Scene.EarlyAccessFeature]: Scene.EarlyAccessFeatures,
    [Scene.Survey]: Scene.Surveys,
    [Scene.SurveyTemplates]: Scene.Surveys,
    [Scene.DataWarehouseTable]: Scene.DataWarehouse,
    [Scene.DataWarehousePosthog]: Scene.DataWarehouse,
    [Scene.DataWarehouseExternal]: Scene.DataWarehouse,
    [Scene.DataWarehouseSavedQueries]: Scene.DataWarehouse,
    [Scene.AppMetrics]: Scene.Apps,
    [Scene.ReplaySingle]: Scene.Replay,
    [Scene.ReplayPlaylist]: Scene.ReplayPlaylist,
}

export const sceneLogic = kea<sceneLogicType>([
    props(
        {} as {
            scenes?: Record<Scene, () => any>
        }
    ),
    path(['scenes', 'sceneLogic']),
    connect(() => ({
        logic: [router, userLogic, preflightLogic, appContextLogic],
        actions: [router, ['locationChanged']],
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
        showUpgradeModal: (featureName: string, featureCaption: string) => ({ featureName, featureCaption }),
        guardAvailableFeature: (
            featureKey: AvailableFeature,
            featureName: string,
            featureCaption: string,
            featureAvailableCallback?: () => void,
            guardOn: {
                cloud: boolean
                selfHosted: boolean
            } = {
                cloud: true,
                selfHosted: true,
            },
            // how much of the feature has been used (eg. number of recording playlists created),
            // which will be compared to the limit for their subscriptions
            currentUsage?: number
        ) => ({ featureKey, featureName, featureCaption, featureAvailableCallback, guardOn, currentUsage }),
        hideUpgradeModal: true,
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
                    [loadedScene.name]: { ...loadedScene, lastTouch: new Date().valueOf() },
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
        upgradeModalFeatureNameAndCaption: [
            null as [string, string] | null,
            {
                showUpgradeModal: (_, { featureName, featureCaption }) => [featureName, featureCaption],
                hideUpgradeModal: () => null,
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
        aliasedActiveScene: [
            (s) => [s.activeScene],
            (activeScene) => (activeScene ? sceneNavAlias[activeScene] || activeScene : null),
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
        showUpgradeModal: ({ featureName }) => {
            eventUsageLogic.actions.reportUpgradeModalShown(featureName)
        },
        guardAvailableFeature: ({
            featureKey,
            featureName,
            featureCaption,
            featureAvailableCallback,
            guardOn,
            currentUsage,
        }) => {
            const { preflight } = preflightLogic.values
            let featureAvailable: boolean
            if (!preflight) {
                featureAvailable = false
            } else if (!guardOn.cloud && preflight.cloud) {
                featureAvailable = true
            } else if (!guardOn.selfHosted && !preflight.cloud) {
                featureAvailable = true
            } else {
                featureAvailable = userLogic.values.hasAvailableFeature(featureKey, currentUsage)
            }
            if (featureAvailable) {
                featureAvailableCallback?.()
            } else {
                actions.showUpgradeModal(featureName, featureCaption)
            }
        },
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
                        if (location.pathname !== urls.projectCreateFirst()) {
                            console.warn('Organization not available, redirecting to project creation')
                            router.actions.replace(urls.projectCreateFirst())
                            return
                        }
                    } else if (
                        teamLogic.values.currentTeam &&
                        !teamLogic.values.currentTeam.is_demo &&
                        !location.pathname.startsWith('/ingestion') &&
                        !location.pathname.startsWith('/onboarding') &&
                        !location.pathname.startsWith('/products') &&
                        !location.pathname.startsWith('/project/settings')
                    ) {
                        if (
                            featureFlagLogic.values.featureFlags[FEATURE_FLAGS.PRODUCT_SPECIFIC_ONBOARDING] ===
                                'test' &&
                            !Object.keys(teamLogic.values.currentTeam.has_completed_onboarding_for || {}).length
                        ) {
                            console.warn('No onboarding completed, redirecting to products')
                            router.actions.replace(urls.products())
                            return
                        } else if (
                            featureFlagLogic.values.featureFlags[FEATURE_FLAGS.PRODUCT_SPECIFIC_ONBOARDING] !==
                                'test' &&
                            !teamLogic.values.currentTeam.completed_snippet_onboarding
                        ) {
                            console.warn('Ingestion tutorial not completed, redirecting to it')
                            router.actions.replace(urls.ingestion())
                            return
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
                    } else {
                        throw error
                    }
                } finally {
                    window.clearTimeout(timeout)
                }
                breakpoint()
                const { default: defaultExport, logic, scene: _scene, ...others } = importedScene

                if (_scene) {
                    loadedScene = { name: scene, ...(_scene as SceneExport), sceneParams: params }
                } else if (defaultExport) {
                    console.warn(`Scene ${scene} not yet converted to use SceneExport!`)
                    loadedScene = {
                        name: scene,
                        component: defaultExport,
                        logic: logic,
                        sceneParams: params,
                    }
                } else {
                    console.warn(`Scene ${scene} not yet converted to use SceneExport!`)
                    loadedScene = {
                        name: scene,
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
            // Remove trailing slash
            const {
                location: { pathname, search, hash },
            } = router.values
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

        mapping['/*'] = (_, __, { method }) => actions.loadScene(Scene.Error404, emptySceneParams, method)

        return mapping
    }),
])
