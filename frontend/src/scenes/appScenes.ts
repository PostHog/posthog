import { Scene } from 'scenes/sceneTypes'
import { preloadedScenes } from 'scenes/scenes'

export const appScenes: Record<Scene, () => any> = {
    [Scene.Error404]: () => ({ default: preloadedScenes[Scene.Error404].component }),
    [Scene.ErrorNetwork]: () => ({ default: preloadedScenes[Scene.ErrorNetwork].component }),
    [Scene.ErrorProjectUnavailable]: () => ({ default: preloadedScenes[Scene.ErrorProjectUnavailable].component }),
    [Scene.Dashboards]: () => import('./dashboard/dashboards/Dashboards'),
    [Scene.Dashboard]: () => import('./dashboard/Dashboard'),
    [Scene.Insight]: () => import('./insights/InsightScene'),
    [Scene.Cohorts]: () => import('./cohorts/Cohorts'),
    [Scene.Cohort]: () => import('./cohorts/Cohort'),
    [Scene.DataManagement]: () => import('./data-management/events/EventDefinitionsTable'),
    [Scene.Events]: () => import('./events/Events'),
    [Scene.Actions]: () => import('./actions/ActionsTable'),
    [Scene.EventDefinitions]: () => import('./data-management/events/EventDefinitionsTable'),
    [Scene.EventDefinition]: () => import('./data-management/definition/DefinitionView'),
    [Scene.PropertyDefinitions]: () => import('./data-management/properties/PropertyDefinitionsTable'),
    [Scene.PropertyDefinition]: () => import('./data-management/definition/DefinitionView'),
    [Scene.DataManagementHistory]: () => import('./data-management/history/History'),
    [Scene.Database]: () => import('./data-management/database/DatabaseScene'),
    [Scene.WebPerformance]: () => import('./performance/WebPerformance'),
    [Scene.Replay]: () => import('./session-recordings/SessionRecordings'),
    [Scene.ReplaySingle]: () => import('./session-recordings/detail/SessionRecordingDetail'),
    [Scene.ReplayPlaylist]: () => import('./session-recordings/playlist/SessionRecordingsPlaylistScene'),
    [Scene.Person]: () => import('./persons/Person'),
    [Scene.Persons]: () => import('./persons/PersonsScene'),
    [Scene.Groups]: () => import('./groups/Groups'),
    [Scene.Group]: () => import('./groups/Group'),
    [Scene.Action]: () => import('./actions/Action'), // TODO
    [Scene.Experiments]: () => import('./experiments/Experiments'),
    [Scene.Experiment]: () => import('./experiments/Experiment'),
    [Scene.FeatureFlags]: () => import('./feature-flags/FeatureFlags'),
    [Scene.FeatureFlag]: () => import('./feature-flags/FeatureFlag'),
    [Scene.EarlyAccessFeatures]: () => import('./early-access-features/EarlyAccessFeatures'),
    [Scene.EarlyAccessFeature]: () => import('./early-access-features/EarlyAccessFeature'),
    [Scene.OrganizationSettings]: () => import('./organization/Settings'),
    [Scene.OrganizationCreateFirst]: () => import('./organization/Create'),
    [Scene.OrganizationCreationConfirm]: () => import('./organization/ConfirmOrganization/ConfirmOrganization'),
    [Scene.ProjectHomepage]: () => import('./project-homepage/ProjectHomepage'),
    [Scene.ProjectSettings]: () => import('./project/Settings'),
    [Scene.ProjectCreateFirst]: () => import('./project/Create'),
    [Scene.SystemStatus]: () => import('./instance/SystemStatus'),
    [Scene.ToolbarLaunch]: () => import('./toolbar-launch/ToolbarLaunch'),
    [Scene.AsyncMigrations]: () => import('./instance/AsyncMigrations/AsyncMigrations'),
    [Scene.DeadLetterQueue]: () => import('./instance/DeadLetterQueue/DeadLetterQueue'),
    [Scene.MySettings]: () => import('./me/Settings'),
    [Scene.Annotations]: () => import('./annotations/Annotations'),
    [Scene.PreflightCheck]: () => import('./PreflightCheck/PreflightCheck'),
    [Scene.Signup]: () => import('./authentication/signup/SignupContainer'),
    [Scene.InviteSignup]: () => import('./authentication/InviteSignup'),
    [Scene.Ingestion]: () => import('./ingestion/IngestionWizard'),
    [Scene.Billing]: () => import('./billing/Billing'),
    [Scene.Plugins]: () => import('./plugins/Plugins'),
    [Scene.FrontendAppScene]: () => import('./apps/FrontendAppScene'),
    [Scene.AppMetrics]: () => import('./apps/AppMetricsScene'),
    [Scene.Login]: () => import('./authentication/Login'),
    [Scene.Login2FA]: () => import('./authentication/Login2FA'),
    [Scene.SavedInsights]: () => import('./saved-insights/SavedInsights'),
    [Scene.PasswordReset]: () => import('./authentication/PasswordReset'),
    [Scene.PasswordResetComplete]: () => import('./authentication/PasswordResetComplete'),
    [Scene.Unsubscribe]: () => import('./Unsubscribe/Unsubscribe'),
    [Scene.IntegrationsRedirect]: () => import('./IntegrationsRedirect/IntegrationsRedirect'),
    [Scene.IngestionWarnings]: () => import('./data-management/ingestion-warnings/IngestionWarningsView'),
    [Scene.DebugQuery]: () => import('./query/QueryScene'),
    [Scene.VerifyEmail]: () => import('./authentication/signup/verify-email/VerifyEmail'),
    [Scene.Feedback]: () => import('./feedback/Feedback'),
}
