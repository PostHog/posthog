import { LogicWrapper } from 'kea'

import type { FileSystemIconType } from '~/queries/schema/schema-general'
import { AccessControlResourceType, ActivityScope } from '~/types'

import { SettingSectionId } from './settings/types'

// The enum here has to match the first and only exported component of the scene.
// If so, we can preload the scene's required chunks in parallel with the scene itself.

export enum Scene {
    Action = 'Action',
    Actions = 'Actions',
    AdvancedActivityLogs = 'AdvancedActivityLogs',
    Annotations = 'Annotations',
    AsyncMigrations = 'AsyncMigrations',
    BatchExport = 'BatchExport',
    BatchExportNew = 'BatchExportNew',
    Billing = 'Billing',
    BillingAuthorizationStatus = 'BillingAuthorizationStatus',
    BillingSection = 'BillingSection',
    Canvas = 'Canvas',
    CLIAuthorize = 'CLIAuthorize',
    Cohort = 'Cohort',
    CohortCalculationHistory = 'CohortCalculationHistory',
    Cohorts = 'Cohorts',
    Comments = 'Comments',
    CustomCss = 'CustomCss',
    CustomerAnalytics = 'CustomerAnalytics',
    Dashboard = 'Dashboard',
    Dashboards = 'Dashboards',
    DataManagement = 'DataManagement',
    DataPipelines = 'DataPipelines',
    DataPipelinesNew = 'DataPipelinesNew',
    DataWarehouse = 'DataWarehouse',
    DataWarehouseRedirect = 'DataWarehouseRedirect',
    DataWarehouseSource = 'DataWarehouseSource',
    DataWarehouseSourceNew = 'DataWarehouseSourceNew',
    DeadLetterQueue = 'DeadLetterQueue',
    DebugHog = 'DebugHog',
    DebugQuery = 'DebugQuery',
    EarlyAccessFeatures = 'EarlyAccessFeatures',
    Error404 = '404',
    ErrorAccessDenied = 'AccessDenied',
    ErrorNetwork = '4xx',
    ErrorProjectUnavailable = 'ProjectUnavailable',
    ErrorTracking = 'ErrorTracking',
    ErrorTrackingConfiguration = 'ErrorTrackingConfiguration',
    ErrorTrackingIssue = 'ErrorTrackingIssue',
    ErrorTrackingIssueFingerprints = 'ErrorTrackingIssueFingerprints',
    EventDefinition = 'EventDefinition',
    EventDefinitions = 'EventDefinitions',
    EventDefinitionEdit = 'EventDefinitionEdit',
    Experiment = 'Experiment',
    Experiments = 'Experiments',
    ExperimentsSharedMetric = 'ExperimentsSharedMetric',
    ExperimentsSharedMetrics = 'ExperimentsSharedMetrics',
    ExploreEvents = 'ExploreEvents',
    FeatureFlag = 'FeatureFlag',
    FeatureFlags = 'FeatureFlags',
    Game368 = 'Game368',
    Group = 'Group',
    Groups = 'Groups',
    GroupsNew = 'GroupsNew',
    Heatmaps = 'Heatmaps',
    Heatmap = 'Heatmap',
    HeatmapNew = 'HeatmapNew',
    HeatmapRecording = 'HeatmapRecording',
    HogFunction = 'HogFunction',
    Insight = 'Insight',
    IntegrationsRedirect = 'IntegrationsRedirect',
    IngestionWarnings = 'IngestionWarnings',
    InviteSignup = 'InviteSignup',
    LegacyPlugin = 'LegacyPlugin',
    Link = 'Link',
    Links = 'Links',
    LiveDebugger = 'LiveDebugger',
    LiveEvents = 'LiveEvents',
    Login = 'Login',
    Login2FA = 'Login2FA',
    EmailMFAVerify = 'EmailMFAVerify',
    Max = 'Max',
    MoveToPostHogCloud = 'MoveToPostHogCloud',
    NewTab = 'NewTab',
    Notebook = 'Notebook',
    Notebooks = 'Notebooks',
    OAuthAuthorize = 'OAuthAuthorize',
    Onboarding = 'Onboarding',
    OrganizationCreateFirst = 'OrganizationCreate',
    OrganizationCreationConfirm = 'OrganizationCreationConfirm',
    PasswordReset = 'PasswordReset',
    PasswordResetComplete = 'PasswordResetComplete',
    Person = 'Person',
    Persons = 'Persons',
    Pipeline = 'Pipeline',
    PipelineNode = 'PipelineNode',
    PipelineNodeNew = 'PipelineNodeNew',
    PreflightCheck = 'PreflightCheck',
    Products = 'Products',
    ProjectCreateFirst = 'ProjectCreate',
    ProjectHomepage = 'ProjectHomepage',
    PropertyDefinition = 'PropertyDefinition',
    PropertyDefinitions = 'PropertyDefinitions',
    PropertyDefinitionEdit = 'PropertyDefinitionEdit',
    Replay = 'Replay',
    ReplayFilePlayback = 'ReplayFilePlayback',
    ReplayPlaylist = 'ReplayPlaylist',
    ReplaySettings = 'ReplaySettings',
    ReplaySingle = 'ReplaySingle',
    RevenueAnalytics = 'RevenueAnalytics',
    SQLEditor = 'SQLEditor',
    SavedInsights = 'SavedInsights',
    SessionAttributionExplorer = 'SessionAttributionExplorer',
    Settings = 'Settings',
    Signup = 'Signup',
    Site = 'Site',
    StartupProgram = 'StartupProgram',
    Survey = 'Survey',
    SurveyTemplates = 'SurveyTemplates',
    Surveys = 'Surveys',
    SystemStatus = 'SystemStatus',
    ToolbarLaunch = 'ToolbarLaunch',
    Unsubscribe = 'Unsubscribe',
    UserInterview = 'UserInterview',
    UserInterviews = 'UserInterviews',
    VerifyEmail = 'VerifyEmail',
    WebAnalytics = 'WebAnalytics',
    WebAnalyticsMarketing = 'WebAnalyticsMarketing',
    WebAnalyticsPageReports = 'WebAnalyticsPageReports',
    WebAnalyticsWebVitals = 'WebAnalyticsWebVitals',
    Endpoints = 'Endpoints',
    Endpoint = 'Endpoint',
    EndpointNew = 'EndpointNew',
    Workflow = 'Workflow',
    Workflows = 'Workflows',
    Wizard = 'Wizard',
    EarlyAccessFeature = 'EarlyAccessFeature',
    EndpointsScene = 'EndpointsScene',
    EndpointsUsage = 'EndpointsUsage',
    Game368Hedgehogs = 'Game368Hedgehogs',
    LLMAnalytics = 'LLMAnalytics',
    LLMAnalyticsDataset = 'LLMAnalyticsDataset',
    LLMAnalyticsDatasets = 'LLMAnalyticsDatasets',
    LLMAnalyticsEvaluation = 'LLMAnalyticsEvaluation',
    LLMAnalyticsEvaluations = 'LLMAnalyticsEvaluations',
    LLMAnalyticsPlayground = 'LLMAnalyticsPlayground',
    LLMAnalyticsTrace = 'LLMAnalyticsTrace',
    LLMAnalyticsUsers = 'LLMAnalyticsUsers',
    Logs = 'Logs',
    ManagedMigration = 'ManagedMigration',
    ManagedMigrationNew = 'ManagedMigrationNew',
    MessagingLibraryTemplate = 'MessagingLibraryTemplate',
    NewAction = 'NewAction',
    TaskDetail = 'TaskDetail',
    TaskTracker = 'TaskTracker',
}

export type SceneComponent<T> = (props: T) => JSX.Element | null
export type SceneProps = Record<string, any>

export interface SceneExport<T = SceneProps> {
    /** component to render for this scene */
    component: SceneComponent<T>
    /** logic to mount for this scene */
    logic?: LogicWrapper
    /** setting section id to open when clicking the settings button */
    settingSectionId?: SettingSectionId
    /** convert URL parameters from scenes.ts into logic props */
    paramsToProps?: (params: SceneParams) => T
    /** when was the scene last touched, unix timestamp for sortability */
    lastTouch?: number
}

// KLUDGE: LoadedScene is used in a logic and therefore cannot accept generics
// we use an untyped SceneProps to satisfy the types
export interface LoadedScene extends SceneExport<SceneProps> {
    id: string
    tabId?: string
    sceneParams: SceneParams
}

export interface SceneTab {
    id: string
    pathname: string
    search: string
    hash: string
    title: string
    active: boolean
    customTitle?: string
    iconType: FileSystemIconType | 'loading' | 'blank'

    sceneId?: string
    sceneKey?: string
    sceneParams?: SceneParams
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
    /** Optional static description of the scene or product. Used both in the UI and by Max AI as context on what the scene is for */
    description?: string
    /** Route should only be accessed when logged out (N.B. should be added to posthog/urls.py too) */
    onlyUnauthenticated?: boolean
    /** Route **can** be accessed when logged out (i.e. can be accessed when logged in too; should be added to posthog/urls.py too) */
    allowUnauthenticated?: boolean
    /**
     * If `app`, navigation is shown, and the scene has default padding.
     * If `app-full-scene-height`, navigation is shown, and the scene has default padding and wrapper takes full screen height.
     * If `app-raw`, navigation is shown, but the scene has no padding.
     * If `app-container`, navigation is shown, and the scene is centered with a max width.
     * If `plain`, there's no navigation present, and the scene has no padding.
     * @default 'app'
     */
    layout?: 'app' | 'app-raw' | 'app-container' | 'app-raw-no-header' | 'plain' | 'app-full-scene-height'
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
    /** Default docs path - what the docs side panel will open by default when this scene is active  */
    defaultDocsPath?: string | (() => string) | (() => Promise<string>)
    /** Component import, used only in manifests */
    import?: () => Promise<any>
    /** Custom icon for the tabs */
    iconType?: FileSystemIconType
    /** If true, uses canvas background (--color-bg-surface-primary) for the scene and its tab */
    canvasBackground?: boolean
}

// Map scenes to their access control resource types
export const sceneToAccessControlResourceType: Partial<Record<Scene, AccessControlResourceType>> = {
    // Actions
    [Scene.Action]: AccessControlResourceType.Action,
    [Scene.Actions]: AccessControlResourceType.Action,

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

    // Session recording
    [Scene.Replay]: AccessControlResourceType.SessionRecording,
    [Scene.ReplaySingle]: AccessControlResourceType.SessionRecording,
    [Scene.ReplayPlaylist]: AccessControlResourceType.SessionRecording,

    // Revenue analytics
    [Scene.RevenueAnalytics]: AccessControlResourceType.RevenueAnalytics,

    // Web Analytics
    [Scene.WebAnalytics]: AccessControlResourceType.WebAnalytics,
    [Scene.WebAnalyticsMarketing]: AccessControlResourceType.WebAnalytics,
    [Scene.WebAnalyticsPageReports]: AccessControlResourceType.WebAnalytics,
    [Scene.WebAnalyticsWebVitals]: AccessControlResourceType.WebAnalytics,

    // Surveys
    [Scene.Survey]: AccessControlResourceType.Survey,
    [Scene.Surveys]: AccessControlResourceType.Survey,
    [Scene.SurveyTemplates]: AccessControlResourceType.Survey,

    // Experiments
    [Scene.Experiment]: AccessControlResourceType.Experiment,
    [Scene.Experiments]: AccessControlResourceType.Experiment,
}
