import { Params, Scene, SceneConfig, LoadedScene } from 'scenes/sceneTypes'
import { Error404 as Error404Component } from '~/layout/Error404'
import { ErrorNetwork as ErrorNetworkComponent } from '~/layout/ErrorNetwork'
import { ErrorProjectUnavailable as ErrorProjectUnavailableComponent } from '~/layout/ErrorProjectUnavailable'
import { urls } from 'scenes/urls'

export const emptySceneParams = { params: {}, searchParams: {}, hashParams: {} }

export const preloadedScenes: Record<string, LoadedScene> = {
    [Scene.Error404]: {
        name: Scene.Error404,
        component: Error404Component,
        sceneParams: emptySceneParams,
    },
    [Scene.ErrorNetwork]: {
        name: Scene.ErrorNetwork,
        component: ErrorNetworkComponent,
        sceneParams: emptySceneParams,
    },
    [Scene.ErrorProjectUnavailable]: {
        name: Scene.ErrorProjectUnavailable,
        component: ErrorProjectUnavailableComponent,
        sceneParams: emptySceneParams,
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

    [Scene.Events]: () => import(/* webpackChunkName: 'events' */ './events/EventsTable'),
    [Scene.Actions]: () => import(/* webpackChunkName: 'events' */ './actions/ActionsTable'),
    [Scene.EventStats]: () => import(/* webpackChunkName: 'events' */ './events/EventsVolumeTable'),
    [Scene.EventPropertyStats]: () => import(/* webpackChunkName: 'events' */ './events/PropertiesVolumeTable'),

    [Scene.Sessions]: () => import(/* webpackChunkName: 'sessions' */ './sessions/Sessions'),
    [Scene.SessionRecordings]: () =>
        import(/* webpackChunkName: 'sessionRecordings' */ './session-recordings/SessionRecordings'),
    [Scene.Person]: () => import(/* webpackChunkName: 'person' */ './persons/Person'),
    [Scene.Persons]: () => import(/* webpackChunkName: 'persons' */ './persons/Persons'),
    [Scene.Action]: () => import(/* webpackChunkName: 'action' */ './actions/Action'), // TODO
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
    [Scene.SessionRecordings]: {
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
    '/': urls.insights(),
    '/dashboards': urls.dashboards(),
    '/plugins': urls.plugins(),
    '/actions': '/events/actions',
    '/organization/members': urls.organizationSettings(),
}

export const routes: Record<string, Scene> = {
    [urls.dashboards()]: Scene.Dashboards,
    [urls.dashboard(':id')]: Scene.Dashboard,
    [urls.createAction()]: Scene.Action,
    [urls.action(':id')]: Scene.Action,
    [urls.insights()]: Scene.Insights,
    [urls.insightRouter(':id')]: Scene.InsightRouter,
    [urls.actions()]: Scene.Actions,
    [urls.eventStats()]: Scene.EventStats,
    [urls.eventPropertyStats()]: Scene.EventPropertyStats,
    [urls.events()]: Scene.Events,
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
