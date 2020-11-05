import { kea } from 'kea'
import { router } from 'kea-router'
import { delay } from 'lib/utils'
import { Error404 } from '~/layout/Error404'
import { ErrorNetwork } from '~/layout/ErrorNetwork'
import { userLogic } from './userLogic'

export const scenes = {
    // NB! also update sceneOverride in layout/Sidebar.js if adding new scenes that belong to an old sidebar link

    dashboards: () => import(/* webpackChunkName: 'dashboards' */ './dashboard/Dashboards'),
    dashboard: () => import(/* webpackChunkName: 'dashboard' */ './dashboard/Dashboard'),
    insights: () => import(/* webpackChunkName: 'insights' */ './insights/Insights'),
    cohorts: () => import(/* webpackChunkName: 'cohorts' */ './users/Cohorts'),
    events: () => import(/* webpackChunkName: 'events' */ './events/Events'),
    sessions: () => import(/* webpackChunkName: 'sessions' */ './sessions/Sessions'),
    person: () => import(/* webpackChunkName: 'person' */ './users/Person'),
    persons: () => import(/* webpackChunkName: 'persons' */ './users/People'),
    actions: () => import(/* webpackChunkName: 'actions' */ './actions/Actions'),
    action: () => import(/* webpackChunkName: 'action' */ './actions/Action'),
    liveActions: () => import(/* webpackChunkName: 'liveActions' */ './actions/LiveActions'),
    featureFlags: () => import(/* webpackChunkName: 'featureFlags' */ './experimentation/FeatureFlags'),
    organizationSettings: () => import(/* webpackChunkName: 'organizationSettings' */ './organization/Settings'),
    organizationMembers: () => import(/* webpackChunkName: 'organizationMembers' */ './organization/Members'),
    organizationInvites: () => import(/* webpackChunkName: 'organizationInvites' */ './organization/Invites'),
    projectSettings: () => import(/* webpackChunkName: 'projectSettings' */ './project/Settings'),
    instanceStatus: () => import(/* webpackChunkName: 'instanceStatus' */ './instance/SystemStatus'),
    instanceLicenses: () => import(/* webpackChunkName: 'instanceLicenses' */ './instance/Licenses'),
    mySettings: () => import(/* webpackChunkName: 'mySettings' */ './me/Settings'),
    annotations: () => import(/* webpackChunkName: 'annotations' */ './annotations'),
    preflightCheck: () => import(/* webpackChunkName: 'preflightCheck' */ './PreflightCheck'),
    signup: () => import(/* webpackChunkName: 'signup' */ './Signup'),
    ingestion: () => import(/* webpackChunkName: 'ingestion' */ './ingestion/IngestionWizard'),
    billing: () => import(/* webpackChunkName: 'billing' */ './billing/Billing'),
    plugins: () => import(/* webpackChunkName: 'plugins' */ './plugins/Plugins'),
}

/* List of routes that do not require authentication (N.B. add to posthog/urls.py too) */
export const unauthenticatedRoutes = ['preflightCheck', 'signup']

export const redirects = {
    '/': '/insights',
    '/plugins': '/project/plugins',
}

export const routes = {
    '/dashboard': 'dashboards',
    '/dashboard/:id': 'dashboard',
    '/action/:id': 'action',
    '/action': 'action',
    '/actions/live': 'liveActions',
    '/actions': 'actions',
    '/insights': 'insights',
    '/events': 'events',
    '/sessions': 'sessions',
    '/person_by_id/:id': 'person',
    '/person/*': 'person',
    '/persons': 'persons',
    '/cohorts/new': 'persons',
    '/cohorts': 'cohorts',
    '/feature_flags': 'featureFlags',
    '/annotations': 'annotations',
    '/project/settings': 'projectSettings',
    '/project/plugins': 'plugins',
    '/organization/settings': 'organizationSettings',
    '/organization/members': 'organizationMembers',
    '/organization/invites': 'organizationInvites',
    '/organization/billing': 'billing',
    '/instance/licenses': 'instanceLicenses',
    '/instance/status': 'instanceStatus',
    '/me/settings': 'mySettings',
    '/preflight': 'preflightCheck',
    '/signup': 'signup',
    '/ingestion': 'ingestion',
    '/ingestion/*': 'ingestion',
}

export const sceneLogic = kea({
    actions: {
        loadScene: (scene, params) => ({ scene, params }),
        setScene: (scene, params) => ({ scene, params }),
        setLoadedScene: (scene, loadedScene) => ({ scene, loadedScene }),
        showUpgradeModal: (featureName) => ({ featureName }),
        hideUpgradeModal: true,
        takeToPricing: true,
    },
    reducers: ({ actions }) => ({
        scene: [
            null,
            {
                [actions.setScene]: (_, payload) => payload.scene,
            },
        ],
        params: [
            {},
            {
                [actions.setScene]: (_, payload) => payload.params || {},
            },
        ],
        loadedScenes: [
            {
                404: {
                    component: Error404,
                },
                '4xx': {
                    component: ErrorNetwork,
                },
            },
            {
                [actions.setLoadedScene]: (state, { scene, loadedScene }) => ({ ...state, [scene]: loadedScene }),
            },
        ],
        loadingScene: [
            null,
            {
                [actions.loadScene]: (_, { scene }) => scene,
                [actions.setScene]: () => null,
            },
        ],
        upgradeModalFeatureName: [
            null,
            {
                [actions.showUpgradeModal]: (_, { featureName }) => featureName,
                [actions.hideUpgradeModal]: () => null,
                [actions.takeToPricing]: () => null,
            },
        ],
    }),
    urlToAction: ({ actions }) => {
        const mapping = {}

        for (const [paths, redirect] of Object.entries(redirects)) {
            for (const path of paths.split('|')) {
                mapping[path] = (params) =>
                    router.actions.replace(typeof redirect === 'function' ? redirect(params) : redirect)
            }
        }

        for (const [paths, scene] of Object.entries(routes)) {
            for (const path of paths.split('|')) {
                mapping[path] = (params) => actions.loadScene(scene, params)
            }
        }
        mapping['/*'] = () => actions.loadScene('404', {})

        return mapping
    },
    listeners: ({ values, actions }) => ({
        showUpgradeModal: ({ featureName }) => {
            window.posthog?.capture('upgrade modal shown', { featureName })
        },
        hideUpgradeModal: () => {
            window.posthog?.capture('upgrade modal cancellation')
        },
        takeToPricing: () => {
            window.open(
                `https://posthog.com/pricing?o=${userLogic.values.user?.is_multi_tenancy ? 'cloud' : 'enterprise'}`
            )
            window.posthog?.capture('upgrade modal pricing interaction')
        },
        setScene: () => {
            window.posthog?.capture('$pageview')
        },
        loadScene: async ({ scene, params = {} }, breakpoint) => {
            if (values.scene === scene) {
                actions.setScene(scene, params)
                return
            }

            if (!scenes[scene]) {
                actions.setScene('404', {})
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
                        } else {
                            // First scene, show an error page
                            console.error('App assets regenerated. Showing error page.')
                            actions.setScene('4xx', {})
                        }
                    } else {
                        throw error
                    }
                }
                breakpoint()
                const { default: defaultExport, logic, ...others } = importedScene

                if (defaultExport) {
                    loadedScene = {
                        component: defaultExport,
                        logic: logic,
                    }
                } else {
                    loadedScene = {
                        component:
                            Object.keys(others).length === 1
                                ? others[Object.keys(others)[0]]
                                : values.loadedScenes['404'].component,
                        logic: logic,
                    }
                }
                actions.setLoadedScene(scene, loadedScene)
            }

            const { logic } = loadedScene

            let unmount

            if (logic) {
                // initialize the logic
                unmount = logic.build(params, false).mount()
                try {
                    await breakpoint(100)
                } catch (e) {
                    // if we change the scene while waiting these 100ms, unmount
                    unmount()
                    throw e
                }
            }

            actions.setScene(scene, params)

            if (unmount) {
                // release our hold on this logic after 0.5s as it's by then surely mounted via React
                // or we are anyway in a new scene and don't need it
                await delay(500)
                unmount()
            }
        },
    }),
})
