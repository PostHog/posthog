import { preloadedScenes } from 'scenes/scenes'
import { Scene } from 'scenes/sceneTypes'

export const appScenes: Record<Scene, () => any> = {
    [Scene.Error404]: () => ({ default: preloadedScenes[Scene.Error404].component }),
    [Scene.ErrorNetwork]: () => ({ default: preloadedScenes[Scene.ErrorNetwork].component }),
    [Scene.ErrorProjectUnavailable]: () => ({ default: preloadedScenes[Scene.ErrorProjectUnavailable].component }),
    [Scene.Dashboards]: () => import('./dashboard/dashboards/Dashboards'),
    [Scene.Dashboard]: () => import('./dashboard/Dashboard'),
    [Scene.Insight]: () => import('./insights/InsightScene'),
    [Scene.WebAnalytics]: () => import('./web-analytics/WebAnalyticsScene'),
    [Scene.Cohort]: () => import('./cohorts/Cohort'),
    [Scene.DataManagement]: () => import('./data-management/DataManagementScene'),
    [Scene.Activity]: () => import('./activity/ActivityScene'),
    [Scene.BatchExports]: () => import('./batch_exports/BatchExportsListScene'),
    [Scene.BatchExportEdit]: () => import('./batch_exports/BatchExportEditScene'),
    [Scene.BatchExport]: () => import('./batch_exports/BatchExportScene'),
    [Scene.EventDefinition]: () => import('./data-management/definition/DefinitionView'),
    [Scene.EventDefinitionEdit]: () => import('./data-management/definition/DefinitionEdit'),
    [Scene.PropertyDefinition]: () => import('./data-management/definition/DefinitionView'),
    [Scene.PropertyDefinitionEdit]: () => import('./data-management/definition/DefinitionEdit'),
    [Scene.Replay]: () => import('./session-recordings/SessionRecordings'),
    [Scene.ReplaySingle]: () => import('./session-recordings/detail/SessionRecordingDetail'),
    [Scene.ReplayPlaylist]: () => import('./session-recordings/playlist/SessionRecordingsPlaylistScene'),
    [Scene.ReplayFilePlayback]: () => import('./session-recordings/file-playback/SessionRecordingFilePlaybackScene'),
    [Scene.PersonsManagement]: () => import('./persons-management/PersonsManagementScene'),
    [Scene.Person]: () => import('./persons/PersonScene'),
    [Scene.pipelineNodeDataWarehouseNew]: () => import('./data-warehouse/new/NewSourceWizard'),
    [Scene.PipelineNodeNew]: () => import('./pipeline/PipelineNodeNew'),
    [Scene.Pipeline]: () => import('./pipeline/Pipeline'),
    [Scene.PipelineNode]: () => import('./pipeline/PipelineNode'),
    [Scene.Group]: () => import('./groups/Group'),
    [Scene.Action]: () => import('./actions/Action'),
    [Scene.Experiments]: () => import('./experiments/Experiments'),
    [Scene.Experiment]: () => import('./experiments/Experiment'),
    [Scene.FeatureFlags]: () => import('./feature-flags/FeatureFlags'),
    [Scene.FeatureFlag]: () => import('./feature-flags/FeatureFlag'),
    [Scene.EarlyAccessFeatures]: () => import('./early-access-features/EarlyAccessFeatures'),
    [Scene.EarlyAccessFeature]: () => import('./early-access-features/EarlyAccessFeature'),
    [Scene.ErrorTracking]: () => import('./error-tracking/ErrorTrackingScene'),
    [Scene.ErrorTrackingGroup]: () => import('./error-tracking/ErrorTrackingGroupScene'),
    [Scene.Surveys]: () => import('./surveys/Surveys'),
    [Scene.Survey]: () => import('./surveys/Survey'),
    [Scene.SurveyTemplates]: () => import('./surveys/SurveyTemplates'),
    [Scene.DataWarehouse]: () => import('./data-warehouse/external/DataWarehouseExternalScene'),
    [Scene.DataWarehouseTable]: () => import('./data-warehouse/new/NewSourceWizard'),
    [Scene.DataWarehouseExternal]: () => import('./data-warehouse/external/DataWarehouseExternalScene'),
    [Scene.DataWarehouseSettings]: () => import('./data-warehouse/settings/DataWarehouseSettingsScene'),
    [Scene.DataWarehouseRedirect]: () => import('./data-warehouse/redirect/DataWarehouseRedirectScene'),
    [Scene.dataWarehouseSourceSettings]: () =>
        import('./data-warehouse/settings/source/DataWarehouseSourceSettingsScene'),
    [Scene.OrganizationCreateFirst]: () => import('./organization/Create'),
    [Scene.OrganizationCreationConfirm]: () => import('./organization/ConfirmOrganization/ConfirmOrganization'),
    [Scene.ProjectHomepage]: () => import('./project-homepage/ProjectHomepage'),
    [Scene.ProjectCreateFirst]: () => import('./project/Create'),
    [Scene.SystemStatus]: () => import('./instance/SystemStatus'),
    [Scene.ToolbarLaunch]: () => import('./toolbar-launch/ToolbarLaunch'),
    [Scene.Site]: () => import('./sites/Site'),
    [Scene.AsyncMigrations]: () => import('./instance/AsyncMigrations/AsyncMigrations'),
    [Scene.DeadLetterQueue]: () => import('./instance/DeadLetterQueue/DeadLetterQueue'),
    [Scene.PreflightCheck]: () => import('./PreflightCheck/PreflightCheck'),
    [Scene.Signup]: () => import('./authentication/signup/SignupContainer'),
    [Scene.InviteSignup]: () => import('./authentication/InviteSignup'),
    [Scene.Billing]: () => import('./billing/Billing'),
    [Scene.Apps]: () => import('./plugins/AppsScene'),
    [Scene.FrontendAppScene]: () => import('./apps/FrontendAppScene'),
    [Scene.AppMetrics]: () => import('./apps/AppMetricsScene'),
    [Scene.Login]: () => import('./authentication/Login'),
    [Scene.Login2FA]: () => import('./authentication/Login2FA'),
    [Scene.SavedInsights]: () => import('./saved-insights/SavedInsights'),
    [Scene.PasswordReset]: () => import('./authentication/PasswordReset'),
    [Scene.PasswordResetComplete]: () => import('./authentication/PasswordResetComplete'),
    [Scene.Unsubscribe]: () => import('./Unsubscribe/Unsubscribe'),
    [Scene.IntegrationsRedirect]: () => import('./IntegrationsRedirect/IntegrationsRedirect'),
    [Scene.DebugQuery]: () => import('./debug/DebugScene'),
    [Scene.VerifyEmail]: () => import('./authentication/signup/verify-email/VerifyEmail'),
    [Scene.Notebooks]: () => import('./notebooks/NotebooksScene'),
    [Scene.Notebook]: () => import('./notebooks/NotebookScene'),
    [Scene.Canvas]: () => import('./notebooks/NotebookCanvasScene'),
    [Scene.Products]: () => import('./products/Products'),
    [Scene.Onboarding]: () => import('./onboarding/Onboarding'),
    [Scene.Settings]: () => import('./settings/SettingsScene'),
    [Scene.MoveToPostHogCloud]: () => import('./moveToPostHogCloud/MoveToPostHogCloud'),
    [Scene.Heatmaps]: () => import('./heatmaps/HeatmapsScene'),
    [Scene.SessionAttributionExplorer]: () => import('./web-analytics/SessionDebugger/SessionAttributionExplorerScene'),
}
