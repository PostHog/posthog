import { Scene } from 'scenes/sceneTypes'
import { preloadedScenes } from 'scenes/scenes'

export const appScenes: Record<Scene, () => any> = {
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
