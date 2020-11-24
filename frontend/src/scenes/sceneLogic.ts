import { BuiltLogic, kea } from 'kea'
import { router } from 'kea-router'
import { camelCaseToTitle, delay } from 'lib/utils'
import { Error404 } from '~/layout/Error404'
import { ErrorNetwork } from '~/layout/ErrorNetwork'
import posthog from 'posthog-js'
import { userLogic } from './userLogic'
import { sceneLogicType } from 'types/scenes/sceneLogicType'

export enum Scene {
    // NB! also update sceneOverride in layout/Sidebar.js if adding new scenes that belong to an old sidebar link
    Dashboards = 'dashboards',
    Dashboard = 'dashboard',
    Insights = 'insights',
    Cohorts = 'cohorts',
    Events = 'events',
    Sessions = 'sessions',
    Person = 'person',
    Persons = 'persons',
    Action = 'action',
    FeatureFlags = 'featureFlags',
    OrganizationSettings = 'organizationSettings',
    OrganizationMembers = 'organizationMembers',
    OrganizationInvites = 'organizationInvites',
    OrganizationCreateFirst = 'organizationCreateFirst',
    ProjectSettings = 'projectSettings',
    ProjectCreateFirst = 'projectCreateFirst',
    InstanceStatus = 'instanceStatus',
    InstanceLicenses = 'instanceLicenses',
    MySettings = 'mySettings',
    Annotations = 'annotations',
    PreflightCheck = 'preflightCheck',
    Signup = 'signup',
    Ingestion = 'ingestion',
    Billing = 'billing',
    Plugins = 'plugins',
}

interface LoadedScene {
    component: () => JSX.Element
    logic?: BuiltLogic
}

interface Params {
    [param: string]: any
}

export const scenes: Record<Scene, () => any> = {
    [Scene.Dashboards]: () => import(/* webpackChunkName: 'dashboards' */ './dashboard/Dashboards'),
    [Scene.Dashboard]: () => import(/* webpackChunkName: 'dashboard' */ './dashboard/Dashboard'),
    [Scene.Insights]: () => import(/* webpackChunkName: 'insights' */ './insights/Insights'),
    [Scene.Cohorts]: () => import(/* webpackChunkName: 'cohorts' */ './persons/Cohorts'),
    [Scene.Events]: () => import(/* webpackChunkName: 'events' */ './events/Events'),
    [Scene.Sessions]: () => import(/* webpackChunkName: 'sessions' */ './sessions/Sessions'),
    [Scene.Person]: () => import(/* webpackChunkName: 'person' */ './persons/Person'),
    [Scene.Persons]: () => import(/* webpackChunkName: 'persons' */ './persons/Persons'),
    [Scene.Action]: () => import(/* webpackChunkName: 'action' */ './actions/Action'),
    [Scene.FeatureFlags]: () => import(/* webpackChunkName: 'featureFlags' */ './experimentation/FeatureFlags'),
    [Scene.OrganizationSettings]: () =>
        import(/* webpackChunkName: 'organizationSettings' */ './organization/Settings'),
    [Scene.OrganizationMembers]: () => import(/* webpackChunkName: 'organizationMembers' */ './organization/Members'),
    [Scene.OrganizationInvites]: () => import(/* webpackChunkName: 'organizationInvites' */ './organization/Invites'),
    [Scene.OrganizationCreateFirst]: () =>
        import(/* webpackChunkName: 'organizationCreateFirst' */ './organization/Create'),
    [Scene.ProjectSettings]: () => import(/* webpackChunkName: 'projectSettings' */ './project/Settings'),
    [Scene.ProjectCreateFirst]: () => import(/* webpackChunkName: 'projectCreateFirst' */ './project/Create'),
    [Scene.InstanceStatus]: () => import(/* webpackChunkName: 'instanceStatus' */ './instance/SystemStatus'),
    [Scene.InstanceLicenses]: () => import(/* webpackChunkName: 'instanceLicenses' */ './instance/Licenses'),
    [Scene.MySettings]: () => import(/* webpackChunkName: 'mySettings' */ './me/Settings'),
    [Scene.Annotations]: () => import(/* webpackChunkName: 'annotations' */ './annotations'),
    [Scene.PreflightCheck]: () => import(/* webpackChunkName: 'preflightCheck' */ './PreflightCheck'),
    [Scene.Signup]: () => import(/* webpackChunkName: 'signup' */ './Signup'),
    [Scene.Ingestion]: () => import(/* webpackChunkName: 'ingestion' */ './ingestion/IngestionWizard'),
    [Scene.Billing]: () => import(/* webpackChunkName: 'billing' */ './billing/Billing'),
    [Scene.Plugins]: () => import(/* webpackChunkName: 'plugins' */ './plugins/Plugins'),
}

interface SceneConfig {
    unauthenticated?: boolean // If route is to be accessed when logged out (N.B. add to posthog/urls.py too)
    dark?: boolean // Background is $bg_mid
    plain?: boolean // Only keeps the main content and the top navigation bar
}

export const sceneConfigurations: Partial<Record<Scene, SceneConfig>> = {
    [Scene.PreflightCheck]: {
        unauthenticated: true,
    },
    [Scene.Signup]: {
        unauthenticated: true,
    },
    [Scene.Dashboard]: {
        dark: true,
    },
    [Scene.Insights]: {
        dark: true,
    },
    [Scene.Ingestion]: {
        plain: true,
    },
    [Scene.OrganizationCreateFirst]: {
        plain: true,
    },
    [Scene.ProjectCreateFirst]: {
        plain: true,
    },
}

export const redirects: Record<string, string | ((params: Params) => any)> = {
    '/': '/insights',
    '/plugins': '/project/plugins',
    '/actions': '/events/actions',
}

export const routes: Record<string, Scene> = {
    '/dashboard': Scene.Dashboards,
    '/dashboard/:id': Scene.Dashboard,
    '/action/:id': Scene.Action,
    '/action': Scene.Action,
    '/insights': Scene.Insights,
    '/events': Scene.Events,
    '/events/*': Scene.Events,
    '/sessions': Scene.Sessions,
    '/person_by_id/:id': Scene.Person,
    '/person/*': Scene.Person,
    '/persons': Scene.Persons,
    '/cohorts/new': Scene.Persons,
    '/cohorts': Scene.Cohorts,
    '/feature_flags': Scene.FeatureFlags,
    '/annotations': Scene.Annotations,
    '/project/settings': Scene.ProjectSettings,
    '/project/plugins': Scene.Plugins,
    '/project/create': Scene.ProjectCreateFirst,
    '/organization/settings': Scene.OrganizationSettings,
    '/organization/members': Scene.OrganizationMembers,
    '/organization/invites': Scene.OrganizationInvites,
    '/organization/billing': Scene.Billing,
    '/organization/create': Scene.OrganizationCreateFirst,
    '/instance/licenses': Scene.InstanceLicenses,
    '/instance/status': Scene.InstanceStatus,
    '/me/settings': Scene.MySettings,
    '/preflight': Scene.PreflightCheck,
    '/signup': Scene.Signup,
    '/ingestion': Scene.Ingestion,
    '/ingestion/*': Scene.Ingestion,
}

export const sceneLogic = kea<sceneLogicType>({
    actions: {
        loadScene: (scene: Scene, params: Params) => ({ scene, params }),
        setScene: (scene: Scene, params: Params) => ({ scene, params }),
        setLoadedScene: (scene: Scene, loadedScene: LoadedScene) => ({ scene, loadedScene }),
        showUpgradeModal: (featureName: string) => ({ featureName }),
        hideUpgradeModal: true,
        takeToPricing: true,
    },
    reducers: ({ actions }) => ({
        scene: [
            null as Scene | null,
            {
                [actions.setScene]: (_, payload) => payload.scene,
            },
        ],
        params: [
            {} as Params,
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
            } as Record<string | number, LoadedScene>,
            {
                [actions.setLoadedScene]: (state, { scene, loadedScene }) => ({ ...state, [scene]: loadedScene }),
            },
        ],
        loadingScene: [
            null as Scene | null,
            {
                [actions.loadScene]: (_, { scene }) => scene,
                [actions.setScene]: () => null,
            },
        ],
        upgradeModalFeatureName: [
            null as string | null,
            {
                [actions.showUpgradeModal]: (_, { featureName }) => featureName,
                [actions.hideUpgradeModal]: () => null,
                [actions.takeToPricing]: () => null,
            },
        ],
    }),
    selectors: () => ({
        sceneConfig: [
            (selectors) => [selectors.scene],
            (scene: Scene): SceneConfig => {
                return sceneConfigurations[scene] ?? {}
            },
        ],
    }),
    urlToAction: ({ actions }) => {
        const mapping: Record<string, (params: Params) => any> = {}

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
            posthog.capture('upgrade modal shown', { featureName })
        },
        hideUpgradeModal: () => {
            posthog.capture('upgrade modal cancellation')
        },
        takeToPricing: () => {
            posthog.capture('upgrade modal pricing interaction')
            if (userLogic.values.user?.is_multi_tenancy) {
                return router.actions.push('/organization/billing')
            }
            window.open(`https://posthog.com/pricing?o=enterprise`)
        },
        setScene: () => {
            posthog.capture('$pageview')
            document.title = values.scene ? `${camelCaseToTitle(values.scene)} • PostHog` : 'PostHog'
        },
        loadScene: async ({ scene, params = {} }: { scene: Scene; params: Params }, breakpoint) => {
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
