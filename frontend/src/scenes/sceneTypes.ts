import { LogicWrapper } from 'kea'

import { AccessControlResourceType, ActivityScope } from '~/types'

import { SettingSectionId } from './settings/types'

// The enum here has to match the first and only exported component of the scene.
// If so, we can preload the scene's required chunks in parallel with the scene itself.

export enum Scene {
    Error404 = '404',
    ErrorAccessDenied = 'AccessDenied',
    ErrorNetwork = '4xx',
    ErrorProjectUnavailable = 'ProjectUnavailable',
    ErrorTracking = 'ErrorTracking',
    ErrorTrackingIssue = 'ErrorTrackingIssue',
    ErrorTrackingConfiguration = 'ErrorTrackingConfiguration',
    Dashboards = 'Dashboards',
    Dashboard = 'Dashboard',
    Insight = 'Insight',
    WebAnalytics = 'WebAnalytics',
    WebAnalyticsWebVitals = 'WebAnalyticsWebVitals',
    WebAnalyticsMarketing = 'WebAnalyticsMarketing',
    WebAnalyticsPageReports = 'WebAnalyticsPageReports',
    RevenueAnalytics = 'RevenueAnalytics',
    Cohort = 'Cohort',
    Activity = 'Activity',
    DataManagement = 'DataManagement',
    EventDefinition = 'EventDefinition',
    EventDefinitionEdit = 'EventDefinitionEdit',
    PropertyDefinition = 'PropertyDefinition',
    PropertyDefinitionEdit = 'PropertyDefinitionEdit',
    Replay = 'Replay',
    ReplaySingle = 'ReplaySingle',
    ReplayPlaylist = 'ReplayPlaylist',
    ReplayFilePlayback = 'ReplayFilePlayback',
    ReplaySettings = 'ReplaySettings',
    CustomCss = 'CustomCss',
    PersonsManagement = 'PersonsManagement',
    Person = 'Person',
    PipelineNodeNew = 'PipelineNodeNew',
    Pipeline = 'Pipeline',
    PipelineNode = 'PipelineNode',
    Groups = 'Groups',
    Group = 'Group',
    Action = 'Action',
    EarlyAccessFeatures = 'EarlyAccessFeatures',
    Experiments = 'Experiments',
    ExperimentsSharedMetrics = 'ExperimentsSharedMetrics',
    ExperimentsSharedMetric = 'ExperimentsSharedMetric',
    Experiment = 'Experiment',
    FeatureFlags = 'FeatureFlags',
    FeatureFlag = 'FeatureFlag',
    Surveys = 'Surveys',
    Survey = 'Survey',
    SurveyTemplates = 'SurveyTemplates',
    SQLEditor = 'SQLEditor',
    DataWarehouseRedirect = 'DataWarehouseRedirect',
    OrganizationCreateFirst = 'OrganizationCreate',
    ProjectHomepage = 'ProjectHomepage',
    Max = 'Max',
    ProjectCreateFirst = 'ProjectCreate',
    SystemStatus = 'SystemStatus',
    AsyncMigrations = 'AsyncMigrations',
    DeadLetterQueue = 'DeadLetterQueue',
    Billing = 'Billing',
    BillingSection = 'BillingSection',
    BillingAuthorizationStatus = 'BillingAuthorizationStatus',
    SavedInsights = 'SavedInsights',
    ToolbarLaunch = 'ToolbarLaunch',
    Site = 'Site',
    IntegrationsRedirect = 'IntegrationsRedirect',
    // Authentication, onboarding & initialization routes
    Login = 'Login',
    Login2FA = 'Login2FA',
    Signup = 'Signup',
    InviteSignup = 'InviteSignup',
    PasswordReset = 'PasswordReset',
    PasswordResetComplete = 'PasswordResetComplete',
    PreflightCheck = 'PreflightCheck',
    OrganizationCreationConfirm = 'OrganizationCreationConfirm',
    Unsubscribe = 'Unsubscribe',
    DebugQuery = 'DebugQuery',
    DebugHog = 'DebugHog',
    VerifyEmail = 'VerifyEmail',
    Notebooks = 'Notebooks',
    Notebook = 'Notebook',
    Canvas = 'Canvas',
    Products = 'Products',
    Onboarding = 'Onboarding',
    Settings = 'Settings',
    MoveToPostHogCloud = 'MoveToPostHogCloud',
    Heatmaps = 'Heatmaps',
    Links = 'Links',
    Link = 'Link',
    SessionAttributionExplorer = 'SessionAttributionExplorer',
    Messaging = 'Messaging',
    MessagingCampaign = 'MessagingCampaign',
    Wizard = 'Wizard',
    StartupProgram = 'StartupProgram',
    HogFunction = 'HogFunction',
    DataPipelines = 'DataPipelines',
    DataPipelinesNew = 'DataPipelinesNew',
    DataWarehouseSource = 'DataWarehouseSource',
    DataWarehouseSourceNew = 'DataWarehouseSourceNew',
    LegacyPlugin = 'LegacyPlugin',
    BatchExport = 'BatchExport',
    BatchExportNew = 'BatchExportNew',
    UserInterviews = 'UserInterviews',
    UserInterview = 'UserInterview',
    Game368 = 'Game368',
}

export type SceneProps = Record<string, any>

export type SceneComponent = (params?: SceneProps) => JSX.Element | null

export interface SceneExport {
    /** component to render for this scene */
    component: SceneComponent
    /** logic to mount for this scene */
    logic?: LogicWrapper
    /** setting section id to open when clicking the settings button */
    settingSectionId?: SettingSectionId
    /** convert URL parameters from scenes.ts into logic props */
    paramsToProps?: (params: SceneParams) => SceneProps
    /** when was the scene last touched, unix timestamp for sortability */
    lastTouch?: number
}

export interface LoadedScene extends SceneExport {
    id: string
    sceneParams: SceneParams
}

export interface SceneParams {
    params: Record<string, any>
    searchParams: Record<string, any>
    hashParams: Record<string, any>
}

export interface Params {
    [param: string]: any
}

export interface SceneConfig {
    /** Custom name for the scene */
    name?: string
    /** Route should only be accessed when logged out (N.B. should be added to posthog/urls.py too) */
    onlyUnauthenticated?: boolean
    /** Route **can** be accessed when logged out (i.e. can be accessed when logged in too; should be added to posthog/urls.py too) */
    allowUnauthenticated?: boolean
    /**
     * If `app`, navigation is shown, and the scene has default padding.
     * If `app-raw`, navigation is shown, but the scene has no padding.
     * If `app-container`, navigation is shown, and the scene is centered with a max width.
     * If `plain`, there's no navigation present, and the scene has no padding.
     * @default 'app'
     */
    layout?: 'app' | 'app-raw' | 'app-container' | 'app-raw-no-header' | 'plain'
    /** Hides project notice (ProjectNotice.tsx). */
    hideProjectNotice?: boolean
    /** Hides billing notice (BillingAlertsV2.tsx). */
    hideBillingNotice?: boolean
    /** Personal account management (used e.g. by breadcrumbs) */
    personal?: boolean
    /** Instance management (used e.g. by breadcrumbs) */
    instanceLevel?: boolean
    /** Route requires organization access (used e.g. by breadcrumbs) */
    organizationBased?: boolean
    /** Route requires project access (used e.g. by breadcrumbs). `true` implies also `organizationBased` */
    projectBased?: boolean
    /** Set the scope of the activity (affects activity and discussion panel) */
    activityScope?: ActivityScope | string
    /** Default docs path - what the docs side panel will open by default if this scene is active  */
    defaultDocsPath?: string
    /** Component import, used only in manifests */
    import?: () => Promise<any>
}

// Map scenes to their access control resource types
export const sceneToAccessControlResourceType: Partial<Record<Scene, AccessControlResourceType>> = {
    // Feature flags
    [Scene.FeatureFlag]: AccessControlResourceType.FeatureFlag,
    [Scene.FeatureFlags]: AccessControlResourceType.FeatureFlag,

    // Dashboards
    [Scene.Dashboard]: AccessControlResourceType.Dashboard,
    [Scene.Dashboards]: AccessControlResourceType.Dashboard,

    // Insights
    [Scene.Insight]: AccessControlResourceType.Insight,
    [Scene.SavedInsights]: AccessControlResourceType.Insight,

    // Notebooks
    [Scene.Notebook]: AccessControlResourceType.Notebook,
    [Scene.Notebooks]: AccessControlResourceType.Notebook,
}
