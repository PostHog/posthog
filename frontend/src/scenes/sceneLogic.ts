import { kea, LogicWrapper } from 'kea'
import { router } from 'kea-router'
import { identifierToHuman, delay } from 'lib/utils'
import { Error404 as Error404Component } from '~/layout/Error404'
import { ErrorNetwork as ErrorNetworkComponent } from '~/layout/ErrorNetwork'
import posthog from 'posthog-js'
import { sceneLogicType } from './sceneLogicType'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { preflightLogic } from './PreflightCheck/logic'
import { AvailableFeature } from '~/types'
import { userLogic } from './userLogic'
import { afterLoginRedirect } from './authentication/loginLogic'
import { ErrorProjectUnavailable as ErrorProjectUnavailableComponent } from '../layout/ErrorProjectUnavailable'
import { teamLogic } from './teamLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

export enum Scene {
    Error404 = '404',
    ErrorNetwork = '4xx',
    ErrorProjectUnavailable = 'projectUnavailable',
    Dashboards = 'dashboards',
    Dashboard = 'dashboard',
    Insights = 'insights',
    InsightRouter = 'insightRouter',
    Cohorts = 'cohorts',
    Events = 'events',
    Sessions = 'sessions',
    SessionRecordings = 'sessionRecordings',
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
    SavedInsights = 'savedInsights',
    // Authentication & onboarding routes
    Login = 'login',
    Signup = 'signup',
    InviteSignup = 'inviteSignup',
    PasswordReset = 'passwordReset',
    PasswordResetComplete = 'passwordResetComplete',
    PreflightCheck = 'preflightCheck',
    Ingestion = 'ingestion',
    OnboardingSetup = 'onboardingSetup',
    Personalization = 'personalization',
}

const preloadedScenes: Record<string, LoadedScene> = {
    [Scene.Error404]: {
        component: Error404Component,
    },
    [Scene.ErrorNetwork]: {
        component: ErrorNetworkComponent,
    },
    [Scene.ErrorProjectUnavailable]: {
        component: ErrorProjectUnavailableComponent,
    },
}

export const scenes: Record<Scene, () => any> = {
    [Scene.Error404]: () => ({ default: preloadedScenes[Scene.Error404].component }),
    [Scene.ErrorNetwork]: () => ({ default: preloadedScenes[Scene.ErrorNetwork].component }),
    [Scene.ErrorProjectUnavailable]: () => ({ default: preloadedScenes[Scene.ErrorProjectUnavailable].component }),
    [Scene.Dashboards]: () => import(/* webpackChunkName: 'dashboards' */ './dashboard/Dashboards'),
    [Scene.Dashboard]: () => import(/* webpackChunkName: 'dashboard' */ './dashboard/Dashboard'),
    [Scene.Insights]: () => import(/* webpackChunkName: 'insights' */ './insights/Insights'),
    [Scene.InsightRouter]: () => import(/* webpackChunkName: 'insightRouter' */ './insights/InsightRouter'),
    [Scene.Cohorts]: () => import(/* webpackChunkName: 'cohorts' */ './cohorts/Cohorts'),
    [Scene.Events]: () => import(/* webpackChunkName: 'events' */ './events/Events'),
    [Scene.Sessions]: () => import(/* webpackChunkName: 'sessions' */ './sessions/Sessions'),
    [Scene.SessionRecordings]: () =>
        import(/* webpackChunkName: 'sessionRecordings' */ './sessionRecordings/SessionRecordings'),
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
    [Scene.SavedInsights]: () => import(/* webpackChunkName: 'savedInsights' */ './saved-insights/SavedInsights'),
    [Scene.PasswordReset]: () => import(/* webpackChunkName: 'passwordReset' */ './authentication/PasswordReset'),
    [Scene.PasswordResetComplete]: () =>
        import(/* webpackChunkName: 'passwordResetComplete' */ './authentication/PasswordResetComplete'),
}

interface LoadedScene {
    component: () => JSX.Element
    logic?: LogicWrapper
}

interface Params {
    [param: string]: any
}

interface SceneConfig {
    /** Route should only be accessed when logged out (N.B. should be added to posthog/urls.py too) */
    onlyUnauthenticated?: boolean
    /** Route **can** be accessed when logged out (i.e. can be accessed when logged in too; should be added to posthog/urls.py too) */
    allowUnauthenticated?: boolean
    /** Background is $bg_mid */
    dark?: boolean
    /** Only keeps the main content and the top navigation bar */
    plain?: boolean
    /** Hides the top navigation bar (regardless of whether `plain` is `true` or not) */
    hideTopNav?: boolean
    /** Hides demo project warnings (DemoWarning.tsx) */
    hideDemoWarnings?: boolean
    /** Route requires project access */
    projectBased?: boolean
}

export const sceneConfigurations: Partial<Record<Scene, SceneConfig>> = {
    // Project-based routes
    [Scene.Dashboards]: {
        projectBased: true,
    },
    [Scene.Dashboard]: {
        projectBased: true,
    },
    [Scene.Insights]: {
        projectBased: true,
        dark: true,
    },
    [Scene.Cohorts]: {
        projectBased: true,
    },
    [Scene.Events]: {
        projectBased: true,
    },
    [Scene.Sessions]: {
        projectBased: true,
    },
    [Scene.Person]: {
        projectBased: true,
    },
    [Scene.Persons]: {
        projectBased: true,
    },
    [Scene.Action]: {
        projectBased: true,
    },
    [Scene.FeatureFlags]: {
        projectBased: true,
    },
    [Scene.FeatureFlag]: {
        projectBased: true,
    },
    [Scene.Annotations]: {
        projectBased: true,
    },
    [Scene.Plugins]: {
        projectBased: true,
    },
    [Scene.SavedInsights]: {
        projectBased: true,
    },
    [Scene.ProjectSettings]: {
        projectBased: true,
        hideDemoWarnings: true,
    },
    [Scene.InsightRouter]: {
        projectBased: true,
        dark: true,
    },
    [Scene.Personalization]: {
        projectBased: true,
        plain: true,
        hideTopNav: true,
    },
    [Scene.Ingestion]: {
        projectBased: true,
        plain: true,
    },
    [Scene.OnboardingSetup]: {
        projectBased: true,
        hideDemoWarnings: true,
    },
    // Organization-based routes
    [Scene.OrganizationCreateFirst]: {
        plain: true,
    },
    [Scene.ProjectCreateFirst]: {
        plain: true,
    },
    [Scene.Billing]: {
        hideDemoWarnings: true,
    },
    // Onboarding/setup routes
    [Scene.Login]: {
        onlyUnauthenticated: true,
    },
    [Scene.Signup]: {
        onlyUnauthenticated: true,
    },
    [Scene.PreflightCheck]: {
        onlyUnauthenticated: true,
    },
    [Scene.PasswordReset]: {
        allowUnauthenticated: true,
    },
    [Scene.PasswordResetComplete]: {
        allowUnauthenticated: true,
    },
    [Scene.InviteSignup]: {
        allowUnauthenticated: true,
        plain: true,
    },
}

export const redirects: Record<string, string | ((params: Params) => string)> = {
    '/': '/insights',
    '/dashboards': '/dashboard', // TODO: For consistency this should be the default, but we should make sure /dashboard keeps working
    '/plugins': '/project/plugins',
    '/actions': '/events/actions',
    '/organization/members': '/organization/settings',
}

export const routes: Record<string, Scene> = {
    [urls.dashboards()]: Scene.Dashboards,
    [urls.dashboard(':id')]: Scene.Dashboard,
    [urls.createAction()]: Scene.Action,
    [urls.action(':id')]: Scene.Action,
    [urls.insights()]: Scene.Insights,
    [urls.insightRouter(':id')]: Scene.InsightRouter,
    [urls.events()]: Scene.Events,
    [urls.events() + '/*']: Scene.Events,
    [urls.sessions()]: Scene.Sessions,
    [urls.sessionRecordings()]: Scene.SessionRecordings,
    [urls.person('*')]: Scene.Person,
    [urls.persons()]: Scene.Persons,
    [urls.cohort(':id')]: Scene.Cohorts,
    [urls.cohorts()]: Scene.Cohorts,
    [urls.featureFlags()]: Scene.FeatureFlags,
    [urls.featureFlag(':id')]: Scene.FeatureFlag,
    [urls.annotations()]: Scene.Annotations,
    [urls.projectSettings()]: Scene.ProjectSettings,
    [urls.plugins()]: Scene.Plugins,
    [urls.projectCreateFirst()]: Scene.ProjectCreateFirst,
    [urls.organizationSettings()]: Scene.OrganizationSettings,
    [urls.organizationBilling()]: Scene.Billing,
    [urls.organizationCreateFirst()]: Scene.OrganizationCreateFirst,
    [urls.instanceLicenses()]: Scene.InstanceLicenses,
    [urls.systemStatus()]: Scene.SystemStatus,
    [urls.systemStatusPage(':id')]: Scene.SystemStatus,
    [urls.mySettings()]: Scene.MySettings,
    [urls.savedInsights()]: Scene.SavedInsights,
    // Onboarding / setup routes
    [urls.login()]: Scene.Login,
    [urls.preflight()]: Scene.PreflightCheck,
    [urls.signup()]: Scene.Signup,
    [urls.inviteSignup(':id')]: Scene.InviteSignup,
    [urls.passwordReset()]: Scene.PasswordReset,
    [urls.passwordResetComplete(':uuid', ':token')]: Scene.PasswordResetComplete,
    [urls.personalization()]: Scene.Personalization,
    [urls.ingestion()]: Scene.Ingestion,
    [urls.ingestion() + '/*']: Scene.Ingestion,
    [urls.onboardingSetup()]: Scene.OnboardingSetup,
}

export const sceneLogic = kea<sceneLogicType<LoadedScene, Params, Scene, SceneConfig>>({
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
        setPageTitle: ({ title }) => {
            document.title = title ? `${title} • PostHog` : 'PostHog'
        },
    }),
})
