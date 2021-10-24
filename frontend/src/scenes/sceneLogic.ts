import { kea } from 'kea'
import { router } from 'kea-router'
import { identifierToHuman } from 'lib/utils'
import posthog from 'posthog-js'
import { sceneLogicType } from './sceneLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from './PreflightCheck/logic'
import { AvailableFeature } from '~/types'
import { userLogic } from './userLogic'
import { afterLoginRedirect } from './authentication/loginLogic'
import { teamLogic } from './teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import { SceneExport, Params, Scene, SceneConfig } from 'scenes/sceneTypes'
import { preloadedScenes, redirects, routes, sceneConfigurations, scenes } from 'scenes/scenes'

export const sceneLogic = kea<sceneLogicType>({
    actions: {
        /* 1. Prepares to open the scene, as the listener may override and do something
            else (e.g. redirecting if unauthenticated), then calls (2) `loadScene`*/
        openScene: (scene: Scene, params: Params) => ({ scene, params }),
        // 2. Start loading the scene's Javascript and mount any logic, then calls (3) `setScene`
        loadScene: (scene: Scene, params: Params) => ({ scene, params }),
        // 3. Set the `scene` reducer
        setScene: (scene: Scene, params: Params) => ({ scene, params }),
        setLoadedScene: (scene: Scene, sceneExport: SceneExport, params: Params) => ({ scene, sceneExport, params }),
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
            }
        ) => ({ featureKey, featureName, featureCaption, featureAvailableCallback, guardOn }),
        hideUpgradeModal: true,
        takeToPricing: true,
        setPageTitle: (title: string) => ({ title }),
    },
    reducers: {
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
                              [scene]: { ...state[scene], params },
                          }
                        : state,
                setLoadedScene: (state, { scene, sceneExport, params }) => ({
                    ...state,
                    [scene]: { ...sceneExport, name: scene, params },
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
                takeToPricing: () => null,
            },
        ],
    },
    selectors: {
        sceneConfig: [
            (selectors) => [selectors.scene],
            (scene: Scene): SceneConfig => {
                return sceneConfigurations[scene] ?? {}
            },
        ],
        activeScene: [
            (selectors) => [
                selectors.loadingScene,
                selectors.scene,
                teamLogic.selectors.isCurrentTeamUnavailable,
                featureFlagLogic.selectors.featureFlags,
            ],
            (loadingScene, scene, isCurrentTeamUnavailable) => {
                const baseActiveScene = loadingScene || scene
                return isCurrentTeamUnavailable && baseActiveScene && sceneConfigurations[baseActiveScene]?.projectBased
                    ? Scene.ErrorProjectUnavailable
                    : baseActiveScene
            },
        ],
        params: [
            (s) => [s.activeScene, s.loadedScenes],
            (activeScene, loadedScenes): Record<string, string> =>
                (activeScene && loadedScenes[activeScene]?.params) || {},
        ],
    },
    urlToAction: ({ actions }) => {
        const mapping: Record<string, (params: Params) => any> = {}

        for (const path of Object.keys(redirects)) {
            mapping[path] = (params) => {
                const redirect = redirects[path]
                router.actions.replace(typeof redirect === 'function' ? redirect(params) : redirect)
            }
        }
        for (const [path, scene] of Object.entries(routes)) {
            mapping[path] = (params) => actions.openScene(scene, params)
        }

        mapping['/*'] = () => actions.loadScene(Scene.Error404, {})

        return mapping
    },
    listeners: ({ values, actions }) => ({
        showUpgradeModal: ({ featureName }) => {
            eventUsageLogic.actions.reportUpgradeModalShown(featureName)
        },
        guardAvailableFeature: ({ featureKey, featureName, featureCaption, featureAvailableCallback, guardOn }) => {
            const { preflight } = preflightLogic.values
            let featureAvailable: boolean
            if (!preflight) {
                featureAvailable = false
            } else if (!guardOn.cloud && preflight.cloud) {
                featureAvailable = true
            } else if (!guardOn.selfHosted && !preflight.cloud) {
                featureAvailable = true
            } else {
                featureAvailable = userLogic.values.hasAvailableFeature(featureKey)
            }
            if (featureAvailable) {
                featureAvailableCallback?.()
            } else {
                actions.showUpgradeModal(featureName, featureCaption)
            }
        },
        takeToPricing: () => {
            posthog.capture('upgrade modal pricing interaction')
            if (preflightLogic.values.preflight?.cloud) {
                return router.actions.push('/organization/billing')
            }
            const pricingTab = preflightLogic.values.preflight?.cloud ? 'cloud' : 'vpc'
            window.open(`https://posthog.com/pricing?o=${pricingTab}`)
        },
        setScene: () => {
            posthog.capture('$pageview')
            actions.setPageTitle(identifierToHuman(values.scene || ''))
        },
        openScene: ({ scene, params }) => {
            const sceneConfig = sceneConfigurations[scene] || {}
            const { user } = userLogic.values
            const { preflight } = preflightLogic.values

            if (scene === Scene.Signup && preflight && !preflight.can_create_org) {
                // If user is on an already initiated self-hosted instance, redirect away from signup
                router.actions.replace(urls.login())
                return
            }

            if (user) {
                // If user is already logged in, redirect away from unauthenticated-only routes (e.g. /signup)
                if (sceneConfig.onlyUnauthenticated) {
                    if (scene === Scene.Login) {
                        router.actions.replace(afterLoginRedirect())
                    } else {
                        router.actions.replace(urls.default())
                    }
                    return
                }

                // Redirect to org/project creation if there's no org/project respectively, unless using invite
                if (scene !== Scene.InviteSignup) {
                    if (!user.organization) {
                        if (location.pathname !== urls.organizationCreateFirst()) {
                            router.actions.replace(urls.organizationCreateFirst())
                            return
                        }
                    } else if (teamLogic.values.isCurrentTeamUnavailable) {
                        if (location.pathname !== urls.projectCreateFirst()) {
                            router.actions.replace(urls.projectCreateFirst())
                            return
                        }
                    } else if (
                        teamLogic.values.currentTeam &&
                        !teamLogic.values.currentTeam.completed_snippet_onboarding &&
                        !location.pathname.startsWith('/ingestion') &&
                        !location.pathname.startsWith('/personalization')
                    ) {
                        // If ingestion tutorial not completed, redirect to it
                        router.actions.replace(urls.ingestion())
                        return
                    }
                }
            }

            actions.loadScene(scene, params)
        },
        loadScene: async (
            {
                scene,
                params = {},
            }: {
                scene: Scene
                params: Params
            },
            breakpoint
        ) => {
            if (values.scene === scene) {
                actions.setScene(scene, params)
                return
            }

            if (!scenes[scene]) {
                actions.setScene(Scene.Error404, {})
                return
            }

            let loadedScene = values.loadedScenes[scene]

            if (!loadedScene) {
                let importedScene
                try {
                    importedScene = await scenes[scene]()
                } catch (error) {
                    if (error.name === 'ChunkLoadError') {
                        if (scene !== null) {
                            // We were on another page (not the first loaded scene)
                            console.error('App assets regenerated. Reloading this page.')
                            window.location.reload()
                            return
                        } else {
                            // First scene, show an error page
                            console.error('App assets regenerated. Showing error page.')
                            actions.setScene(Scene.ErrorNetwork, {})
                        }
                    } else {
                        throw error
                    }
                }
                breakpoint()
                const { default: defaultExport, logic, scene: _scene, ...others } = importedScene

                if (_scene) {
                    loadedScene = _scene
                } else if (defaultExport) {
                    console.warn(`Scene ${scene} not yet converted to use SceneExport!`)
                    loadedScene = {
                        name: scene,
                        component: defaultExport,
                        logic: logic,
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
                    }
                    if (Object.keys(others).length > 1) {
                        console.error('There are multiple exports for this scene. Showing 404 instead.')
                    }
                }
                actions.setLoadedScene(scene, loadedScene, params)
            }
            actions.setScene(scene, params)
        },
        setPageTitle: ({ title }) => {
            document.title = title ? `${title} • PostHog` : 'PostHog'
        },
    }),
})
