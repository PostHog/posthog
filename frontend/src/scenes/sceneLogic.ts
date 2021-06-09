import { kea, LogicWrapper } from 'kea'
import { router } from 'kea-router'
import { identifierToHuman, delay } from 'lib/utils'
import { Error404 as Error404Component } from '~/layout/Error404'
import { ErrorNetwork as ErrorNetworkComponent } from '~/layout/ErrorNetwork'
import posthog from 'posthog-js'
import { sceneLogicType } from './sceneLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from './PreflightCheck/logic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { userLogic } from 'scenes/userLogic'
import { afterLoginRedirect } from 'scenes/authentication/loginLogic'

export enum Scene {
    Error404 = '404',
    ErrorNetwork = '4xx',
    Dashboards = 'dashboards',
    Dashboard = 'dashboard',
    DashboardInsight = 'dashboardInsight',
    Insights = 'insights',
    InsightRouter = 'insightRouter',
    Cohorts = 'cohorts',
    Events = 'events',
    Sessions = 'sessions',
    Person = 'person',
    Persons = 'persons',
    Action = 'action',
    FeatureFlags = 'featureFlags',
    FeatureFlag = 'featureFlag',
    OrganizationSettings = 'organizationSettings',
    OrganizationCreateFirst = 'organizationCreateFirst',
    ProjectSettings = 'projectSettings',
    ProjectCreateFirst = 'projectCreateFirst',
    SystemStatus = 'systemStatus',
    InstanceLicenses = 'instanceLicenses',
    MySettings = 'mySettings',
    Annotations = 'annotations',
    Billing = 'billing',
    Plugins = 'plugins',
    // Onboarding / setup routes
    Login = 'login',
    PreflightCheck = 'preflightCheck',
    Signup = 'signup',
    InviteSignup = 'inviteSignup',
    Personalization = 'personalization',
    Ingestion = 'ingestion',
    OnboardingSetup = 'onboardingSetup',
    Home = 'home',
}

interface LoadedScene {
    component: () => JSX.Element
    logic?: LogicWrapper
}

interface Params {
    [param: string]: any
}

const preloadedScenes: Record<string, LoadedScene> = {
    [Scene.Error404]: {
        component: Error404Component,
    },
    [Scene.ErrorNetwork]: {
        component: ErrorNetworkComponent,
    },
}

export const scenes: Record<Scene, () => any> = {
    [Scene.Error404]: () => ({ default: preloadedScenes[Scene.Error404].component }),
    [Scene.ErrorNetwork]: () => ({ default: preloadedScenes[Scene.ErrorNetwork].component }),
    [Scene.Dashboards]: () => import(/* webpackChunkName: 'dashboards' */ './dashboard/Dashboards'),
    [Scene.Dashboard]: () => import(/* webpackChunkName: 'dashboard' */ './dashboard/Dashboard'),
    [Scene.DashboardInsight]: () =>
        import(/* webpackChunkName: 'dashboardInsight' */ './dashboard-insight/DashboardInsight'),
    [Scene.Insights]: () => import(/* webpackChunkName: 'insights' */ './insights/Insights'),
    [Scene.InsightRouter]: () => import(/* webpackChunkName: 'insightRouter' */ './insights/InsightRouter'),
    [Scene.Cohorts]: () => import(/* webpackChunkName: 'cohorts' */ './persons/Cohorts'),
    [Scene.Events]: () => import(/* webpackChunkName: 'events' */ './events/Events'),
    [Scene.Sessions]: () => import(/* webpackChunkName: 'sessions' */ './sessions/Sessions'),
    [Scene.Person]: () => import(/* webpackChunkName: 'person' */ './persons/Person'),
    [Scene.Persons]: () => import(/* webpackChunkName: 'persons' */ './persons/Persons'),
    [Scene.Action]: () => import(/* webpackChunkName: 'action' */ './actions/Action'),
    [Scene.FeatureFlags]: () => import(/* webpackChunkName: 'featureFlags' */ './experimentation/FeatureFlags'),
    [Scene.FeatureFlag]: () => import(/* webpackChunkName: 'featureFlag' */ './experimentation/FeatureFlag'),
    [Scene.OrganizationSettings]: () =>
        import(/* webpackChunkName: 'organizationSettings' */ './organization/Settings'),
    [Scene.OrganizationCreateFirst]: () =>
        import(/* webpackChunkName: 'organizationCreateFirst' */ './organization/Create'),
    [Scene.ProjectSettings]: () => import(/* webpackChunkName: 'projectSettings' */ './project/Settings'),
    [Scene.ProjectCreateFirst]: () => import(/* webpackChunkName: 'projectCreateFirst' */ './project/Create'),
    [Scene.SystemStatus]: () => import(/* webpackChunkName: 'systemStatus' */ './instance/SystemStatus'),
    [Scene.InstanceLicenses]: () => import(/* webpackChunkName: 'instanceLicenses' */ './instance/Licenses'),
    [Scene.MySettings]: () => import(/* webpackChunkName: 'mySettings' */ './me/Settings'),
    [Scene.Annotations]: () => import(/* webpackChunkName: 'annotations' */ './annotations'),
    [Scene.PreflightCheck]: () => import(/* webpackChunkName: 'preflightCheck' */ './PreflightCheck'),
    [Scene.Signup]: () => import(/* webpackChunkName: 'signup' */ './authentication/Signup'),
    [Scene.InviteSignup]: () => import(/* webpackChunkName: 'inviteSignup' */ './authentication/InviteSignup'),
    [Scene.Ingestion]: () => import(/* webpackChunkName: 'ingestion' */ './ingestion/IngestionWizard'),
    [Scene.Billing]: () => import(/* webpackChunkName: 'billing' */ './billing/Billing'),
    [Scene.Plugins]: () => import(/* webpackChunkName: 'plugins' */ './plugins/Plugins'),
    [Scene.Personalization]: () => import(/* webpackChunkName: 'personalization' */ './onboarding/Personalization'),
    [Scene.OnboardingSetup]: () => import(/* webpackChunkName: 'onboardingSetup' */ './onboarding/OnboardingSetup'),
    [Scene.Login]: () => import(/* webpackChunkName: 'login' */ './authentication/Login'),
    [Scene.Home]: () => import(/* webpackChunkName: 'home' */ './onboarding/home/Home'),
}

interface SceneConfig {
    onlyUnauthenticated?: boolean // Route should only be accessed when logged out (N.B. should be added to posthog/urls.py too)
    allowUnauthenticated?: boolean // Route **can** be accessed when logged out (i.e. can be accessed when logged in too; should be added to posthog/urls.py too)
    dark?: boolean // Background is $bg_mid
    plain?: boolean // Only keeps the main content and the top navigation bar
    hideTopNav?: boolean // Hides the top navigation bar (regardless of whether `plain` is `true` or not)
    hideDemoWarnings?: boolean // Hides demo project warnings (DemoWarning.tsx)
}

export const sceneConfigurations: Partial<Record<Scene, SceneConfig>> = {
    [Scene.Insights]: {
        dark: true,
    },
    [Scene.OrganizationCreateFirst]: {
        plain: true,
    },
    [Scene.ProjectCreateFirst]: {
        plain: true,
    },
    [Scene.Billing]: {
        hideDemoWarnings: true,
    },
    // Onboarding / setup routes
    [Scene.Login]: {
        onlyUnauthenticated: true,
    },
    [Scene.PreflightCheck]: {
        onlyUnauthenticated: true,
    },
    [Scene.Signup]: {
        onlyUnauthenticated: true,
    },
    [Scene.InviteSignup]: {
        allowUnauthenticated: true,
        plain: true,
    },
    [Scene.Personalization]: {
        plain: true,
        hideTopNav: true,
    },
    [Scene.Ingestion]: {
        plain: true,
    },
    [Scene.OnboardingSetup]: {
        hideDemoWarnings: true,
    },
    [Scene.ProjectSettings]: {
        hideDemoWarnings: true,
    },
    [Scene.InsightRouter]: {
        dark: true,
    },
}

export const redirects: Record<string, string | ((params: Params) => any)> = {
    '/': '/insights',
    '/plugins': '/project/plugins',
    '/actions': '/events/actions',
    '/organization/members': '/organization/settings',
}

export const routes: Record<string, Scene> = {
    '/dashboard': Scene.Dashboards,
    '/dashboard/:id': Scene.Dashboard,
    '/dashboard_insight/:id': Scene.DashboardInsight,
    '/action/:id': Scene.Action,
    '/action': Scene.Action,
    '/insights': Scene.Insights,
    '/i/:id': Scene.InsightRouter,
    '/events': Scene.Events,
    '/events/*': Scene.Events,
    '/sessions': Scene.Sessions,
    '/person/*': Scene.Person,
    '/persons': Scene.Persons,
    '/cohorts/:id': Scene.Cohorts,
    '/cohorts': Scene.Cohorts,
    '/feature_flags': Scene.FeatureFlags,
    '/feature_flags/:id': Scene.FeatureFlag,
    '/annotations': Scene.Annotations,
    '/project/settings': Scene.ProjectSettings,
    '/project/plugins': Scene.Plugins,
    '/project/create': Scene.ProjectCreateFirst,
    '/organization/settings': Scene.OrganizationSettings,
    '/organization/billing': Scene.Billing,
    '/organization/create': Scene.OrganizationCreateFirst,
    '/instance/licenses': Scene.InstanceLicenses,
    '/instance/status': Scene.SystemStatus,
    '/instance/status/:id': Scene.SystemStatus,
    '/me/settings': Scene.MySettings,
    // Onboarding / setup routes
    '/login': Scene.Login,
    '/preflight': Scene.PreflightCheck,
    '/signup': Scene.Signup,
    '/signup/:id': Scene.InviteSignup,
    '/personalization': Scene.Personalization,
    '/ingestion': Scene.Ingestion,
    '/ingestion/*': Scene.Ingestion,
    '/setup': Scene.OnboardingSetup,
    '/home': Scene.Home,
}

export const sceneLogic = kea<sceneLogicType<Scene, Params, LoadedScene, SceneConfig>>({
    actions: {
        /* 1. Prepares to open the scene, as the listener may override and do something 
            else (e.g. redirecting if unauthenticated), then calls (2) `loadScene`*/
        openScene: (scene: Scene, params: Params) => ({ scene, params }),
        // 2. Start loading the scene's Javascript and mount any logic, then calls (3) `setScene`
        loadScene: (scene: Scene, params: Params) => ({ scene, params }),
        // 3. Set the `scene` reducer
        setScene: (scene: Scene, params: Params) => ({ scene, params }),

        setLoadedScene: (scene: Scene, loadedScene: LoadedScene) => ({ scene, loadedScene }),
        showUpgradeModal: (featureName: string, featureCaption: string) => ({ featureName, featureCaption }),
        hideUpgradeModal: true,
        takeToPricing: true,
    },
    reducers: {
        scene: [
            null as Scene | null,
            {
                setScene: (_, payload) => payload.scene,
            },
        ],
        params: [
            {} as Params,
            {
                setScene: (_, payload) => payload.params || {},
            },
        ],
        loadedScenes: [
            preloadedScenes,
            {
                setLoadedScene: (state, { scene, loadedScene }) => ({ ...state, [scene]: loadedScene }),
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
        activeScene: [(s) => [s.loadingScene, s.scene], (loadingScene, scene) => loadingScene || scene],
    },
    urlToAction: ({ actions }) => {
        const mapping: Record<string, (params: Params) => any> = {}

        for (const path of Object.keys(redirects)) {
            mapping[path] = (params) => {
                let redirect = redirects[path]

                if (path === '/' && featureFlagLogic.values.featureFlags[FEATURE_FLAGS.PROJECT_HOME]) {
                    redirect = '/home'
                }

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
            document.title = values.scene ? `${identifierToHuman(values.scene)} • PostHog` : 'PostHog'
        },
        openScene: ({ scene, params }) => {
            const sceneConfig = sceneConfigurations[scene] || {}
            const { user } = userLogic.values
            const { preflight } = preflightLogic.values

            if (scene === Scene.Signup && preflight && !preflight.cloud && preflight.initiated) {
                // If user is on an already initiated self-hosted instance, redirect away from signup
                router.actions.replace('/login')
                return
            }

            if (user) {
                // If user is already logged in, redirect away from unauthenticated-only routes (e.g. /signup)
                if (sceneConfig.onlyUnauthenticated) {
                    if (scene === Scene.Login) {
                        router.actions.replace(afterLoginRedirect())
                    } else {
                        router.actions.replace('/')
                    }
                    return
                }

                // Redirect to org/project creation if there's no org/project respectively, unless using invite
                if (scene !== Scene.InviteSignup) {
                    if (!user.organization) {
                        if (location.pathname !== '/organization/create') {
                            router.actions.replace('/organization/create')
                            return
                        }
                    } else if (!user.team) {
                        if (location.pathname !== '/project/create') {
                            router.actions.replace('/project/create')
                            return
                        }
                    } else if (
                        !user.team.completed_snippet_onboarding &&
                        !location.pathname.startsWith('/ingestion') &&
                        !location.pathname.startsWith('/personalization')
                    ) {
                        // If ingestion tutorial not completed, redirect to it
                        router.actions.replace('/ingestion')
                        return
                    }
                }
            }

            actions.loadScene(scene, params)
        },
        loadScene: async ({ scene, params = {} }: { scene: Scene; params: Params }, breakpoint) => {
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
                                : values.loadedScenes[Scene.Error404].component,
                        logic: logic,
                    }
                    if (Object.keys(others).length > 1) {
                        console.error('There are multiple exports for this scene. Showing 404 instead.')
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
