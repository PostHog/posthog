import { LogicWrapper } from 'kea'

import type { FileSystemIconType, ProductKey } from '~/queries/schema/schema-general'
import { AccessControlResourceType, ActivityScope } from '~/types'

// The enum here has to match the first and only exported component of the scene.
// If so, we can preload the scene's required chunks in parallel with the scene itself.

export enum Scene {
    Action = 'Action',
    Actions = 'Actions',
    AdvancedActivityLogs = 'AdvancedActivityLogs',
    AgenticAccountMismatch = 'AgenticAccountMismatch',
    AgenticAuthorize = 'AgenticAuthorize',
    AIGateway = 'AIGateway',
    Annotations = 'Annotations',
    Approval = 'Approval',
    AsyncMigrations = 'AsyncMigrations',
    BatchExport = 'BatchExport',
    BatchExportNew = 'BatchExportNew',
    Billing = 'Billing',
    BillingAuthorizationStatus = 'BillingAuthorizationStatus',
    BillingSection = 'BillingSection',
    Canvas = 'Canvas',
    CLIAuthorize = 'CLIAuthorize',
    CLILive = 'CLILive',
    Cohort = 'Cohort',
    CohortCalculationHistory = 'CohortCalculationHistory',
    Cohorts = 'Cohorts',
    Comments = 'Comments',
    CustomCss = 'CustomCss',
    CustomerAnalytics = 'CustomerAnalytics',
    CustomerAnalyticsConfiguration = 'CustomerAnalyticsConfiguration',
    CustomerJourneyBuilder = 'CustomerJourneyBuilder',
    Dashboard = 'Dashboard',
    Dashboards = 'Dashboards',
    DashboardTemplateCopy = 'DashboardTemplateCopy',
    DataManagement = 'DataManagement',
    DataPipelinesNew = 'DataPipelinesNew',
    DataOps = 'DataOps',
    DataWarehouseRedirect = 'DataWarehouseRedirect',
    DataWarehouseSource = 'DataWarehouseSource',
    DataWarehouseSourceConnect = 'DataWarehouseSourceConnect',
    DataWarehouseSourceNew = 'DataWarehouseSourceNew',
    DataWarehouseSourceSchema = 'DataWarehouseSourceSchema',
    DeadLetterQueue = 'DeadLetterQueue',
    Destinations = 'Destinations',
    DebugHog = 'DebugHog',
    DebugQuery = 'DebugQuery',
    EarlyAccessFeatures = 'EarlyAccessFeatures',
    Error404 = '404',
    ErrorAccessDenied = 'AccessDenied',
    ErrorNetwork = '4xx',
    ErrorProjectUnavailable = 'ProjectUnavailable',
    ErrorTracking = 'ErrorTracking',
    ErrorTrackingIssue = 'ErrorTrackingIssue',
    ErrorTrackingIssueFingerprints = 'ErrorTrackingIssueFingerprints',
    EventDefinition = 'EventDefinition',
    EventDefinitions = 'EventDefinitions',
    EventDefinitionEdit = 'EventDefinitionEdit',
    Experiment = 'Experiment',
    Experiments = 'Experiments',
    Exports = 'Exports',
    Subscriptions = 'Subscriptions',
    Subscription = 'Subscription',
    ExperimentsSharedMetric = 'ExperimentsSharedMetric',
    ExperimentsSharedMetrics = 'ExperimentsSharedMetrics',
    ExploreEvents = 'ExploreEvents',
    ExploreSessions = 'ExploreSessions',
    FeatureFlag = 'FeatureFlag',
    FeatureFlags = 'FeatureFlags',
    Game368 = 'Game368',
    Group = 'Group',
    Groups = 'Groups',
    GroupsNew = 'GroupsNew',
    Heatmaps = 'Heatmaps',
    Heatmap = 'Heatmap',
    Inbox = 'Inbox',
    HeatmapNew = 'HeatmapNew',
    HeatmapRecording = 'HeatmapRecording',
    HogFunction = 'HogFunction',
    Insight = 'Insight',
    InsightQuickStart = 'InsightQuickStart',
    IntegrationsRedirect = 'IntegrationsRedirect',
    IntegrationsLanding = 'IntegrationsLanding',
    StripeConfirmInstall = 'StripeConfirmInstall',
    IngestionWarnings = 'IngestionWarnings',
    InviteSignup = 'InviteSignup',
    BusinessKnowledge = 'BusinessKnowledge',
    LegacyPlugin = 'LegacyPlugin',
    LegalDocuments = 'LegalDocuments',
    LegalDocumentNew = 'LegalDocumentNew',
    Link = 'Link',
    Links = 'Links',
    LiveDebugger = 'LiveDebugger',
    Activity = 'Activity',
    LiveEvents = 'LiveEvents',
    Login = 'Login',
    Login2FA = 'Login2FA',
    EmailMFAVerify = 'EmailMFAVerify',
    MaterializedColumns = 'MaterializedColumns',
    Max = 'Max',
    Models = 'Models',
    NodeDetail = 'NodeDetail',
    MoveToPostHogCloud = 'MoveToPostHogCloud',
    NewTab = 'NewTab',
    Notebook = 'Notebook',
    Notebooks = 'Notebooks',
    OAuthAuthorize = 'OAuthAuthorize',
    Onboarding = 'Onboarding',
    OnboardingCoupon = 'OnboardingCoupon',
    OrganizationCreateFirst = 'OrganizationCreate',
    OrganizationCreationConfirm = 'OrganizationCreationConfirm',
    PasswordReset = 'PasswordReset',
    PasswordResetComplete = 'PasswordResetComplete',
    TwoFactorReset = 'TwoFactorReset',
    Person = 'Person',
    Persons = 'Persons',
    AccountConnected = 'AccountConnected',
    CredentialReview = 'CredentialReview',
    Pipeline = 'Pipeline',
    PipelineStatus = 'PipelineStatus',
    PipelineNode = 'PipelineNode',
    PipelineNodeNew = 'PipelineNodeNew',
    PreflightCheck = 'PreflightCheck',
    ProductTour = 'ProductTour',
    ProductTours = 'ProductTours',
    ProjectCreateFirst = 'ProjectCreate',
    ProjectHomepage = 'ProjectHomepage',
    PropertyDefinition = 'PropertyDefinition',
    PropertyDefinitions = 'PropertyDefinitions',
    PropertyDefinitionEdit = 'PropertyDefinitionEdit',
    QueryPerformance = 'QueryPerformance',
    Replay = 'Replay',
    ReplayFilePlayback = 'ReplayFilePlayback',
    ReplayPlaylist = 'ReplayPlaylist',
    ReplaySettings = 'ReplaySettings',
    ReplaySingle = 'ReplaySingle',
    ReplayKiosk = 'ReplayKiosk',
    ResourceTransfer = 'ResourceTransfer',
    RevenueAnalytics = 'RevenueAnalytics',
    SqlVariableEdit = 'SqlVariableEdit',
    SQLEditor = 'SQLEditor',
    SavedInsights = 'SavedInsights',
    Health = 'Health',
    HealthCategoryDetail = 'HealthCategoryDetail',
    HealthAlerts = 'HealthAlerts',
    SdkHealth = 'SdkHealth',
    SessionAttributionExplorer = 'SessionAttributionExplorer',
    SessionGroupSummariesTable = 'SessionGroupSummariesTable',
    SessionGroupSummary = 'SessionGroupSummary',
    SessionSummaries = 'SessionSummaries',
    SessionProfile = 'SessionProfile',
    Settings = 'Settings',
    Signup = 'Signup',
    Site = 'Site',
    Coupons = 'Coupons',
    Sources = 'Sources',
    StartupProgram = 'StartupProgram',
    Survey = 'Survey',
    SurveyWizard = 'SurveyWizard',
    SurveyFormBuilder = 'SurveyFormBuilder',
    Surveys = 'Surveys',
    SystemStatus = 'SystemStatus',
    ToolbarLaunch = 'ToolbarLaunch',
    Tracing = 'Tracing',
    Metrics = 'Metrics',
    Transformations = 'Transformations',
    EventFiltering = 'EventFiltering',
    Unsubscribe = 'Unsubscribe',
    CodeCanvasLink = 'CodeCanvasLink',
    UserInterview = 'UserInterview',
    UserInterviewResponse = 'UserInterviewResponse',
    UserInterviews = 'UserInterviews',
    VercelConnect = 'VercelConnect',
    VercelLinkError = 'VercelLinkError',
    VerifyEmail = 'VerifyEmail',
    WebAnalytics = 'WebAnalytics',
    WebAnalyticsPageReports = 'WebAnalyticsPageReports',
    WebAnalyticsWebVitals = 'WebAnalyticsWebVitals',
    WebAnalyticsHealth = 'WebAnalyticsHealth',
    WebAnalyticsLive = 'WebAnalyticsLive',
    WebAnalyticsRecap = 'WebAnalyticsRecap',
    WebScripts = 'WebScripts',
    Endpoints = 'Endpoints',
    Endpoint = 'Endpoint',
    Workflow = 'Workflow',
    Workflows = 'Workflows',
    Wizard = 'Wizard',
    EarlyAccessFeature = 'EarlyAccessFeature',
    EndpointsScene = 'EndpointsScene',
    Game368Hedgehogs = 'Game368Hedgehogs',
    AIObservability = 'AIObservability',
    AIObservabilityDataset = 'AIObservabilityDataset',
    AIObservabilityDatasets = 'AIObservabilityDatasets',
    AIObservabilityEvaluation = 'AIObservabilityEvaluation',
    AIObservabilityEvaluations = 'AIObservabilityEvaluations',
    AIObservabilityPlayground = 'AIObservabilityPlayground',
    AIObservabilityTrace = 'AIObservabilityTrace',
    AIObservabilityUsers = 'AIObservabilityUsers',
    Logs = 'Logs',
    MCPAnalytics = 'MCPAnalytics',
    LogsAlertDetail = 'LogsAlertDetail',
    LogsAlertNotificationDetail = 'LogsAlertNotificationDetail',
    LogsSamplingNew = 'LogsSamplingNew',
    LogsSamplingDetail = 'LogsSamplingDetail',
    ManagedMigration = 'ManagedMigration',
    ManagedMigrationNew = 'ManagedMigrationNew',
    MarketingAnalytics = 'MarketingAnalytics',
    MarketingAnalyticsSettings = 'MarketingAnalyticsSettings',
    MessagingLibraryTemplate = 'MessagingLibraryTemplate',
    NewAction = 'NewAction',
    TaskTracker = 'TaskTracker',
    SlackTaskContext = 'SlackTaskContext',
    OrganizationDeactivated = 'OrganizationDeactivated',
    OrganizationPendingDeletion = 'OrganizationPendingDeletion',
    ProjectPendingDeletion = 'ProjectPendingDeletion',
    CustomerJourneyTemplates = 'CustomerJourneyTemplates',
}

export type SceneComponent<T> = (props: T) => JSX.Element | null
export type SceneProps = Record<string, any>

export interface SceneExport<T = SceneProps> {
    /** component to render for this scene */
    component: SceneComponent<T>
    /** logic to mount for this scene */
    logic?: LogicWrapper
    /** product key associated with this scene - used for Quick Start setup tracking */
    productKey?: ProductKey
    /** convert URL parameters from scenes.ts into logic props */
    paramsToProps?: (params: SceneParams) => T
    /** when was the scene last touched, unix timestamp for sortability */
    lastTouch?: number
}

// KLUDGE: LoadedScene is used in a logic and therefore cannot accept generics
// we use an untyped SceneProps to satisfy the types
export interface LoadedScene extends SceneExport<SceneProps> {
    id: string
    sceneParams: SceneParams
}

export interface SceneTab {
    id: string
    pathname: string
    search: string
    hash: string
    title: string
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
     *
     * @default 'app'
     */
    layout?: 'app' | 'app-raw' | 'app-container' | 'app-raw-no-header' | 'plain' | 'app-full-scene-height'
    /** Hides project notice (ProjectNotice.tsx). */
    hideProjectNotice?: boolean
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
    [Scene.DashboardTemplateCopy]: AccessControlResourceType.Dashboard,

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
    [Scene.WebAnalyticsPageReports]: AccessControlResourceType.WebAnalytics,
    [Scene.WebAnalyticsWebVitals]: AccessControlResourceType.WebAnalytics,
    [Scene.WebAnalyticsHealth]: AccessControlResourceType.WebAnalytics,
    [Scene.WebAnalyticsRecap]: AccessControlResourceType.WebAnalytics,

    // Marketing Analytics
    [Scene.MarketingAnalytics]: AccessControlResourceType.WebAnalytics,

    // Surveys
    [Scene.Survey]: AccessControlResourceType.Survey,
    [Scene.Surveys]: AccessControlResourceType.Survey,

    // Endpoints
    [Scene.EndpointsScene]: AccessControlResourceType.Endpoint,

    // Product Tours
    [Scene.ProductTour]: AccessControlResourceType.ProductTour,
    [Scene.ProductTours]: AccessControlResourceType.ProductTour,

    // Experiments
    [Scene.Experiment]: AccessControlResourceType.Experiment,
    [Scene.Experiments]: AccessControlResourceType.Experiment,

    // Exports
    [Scene.Exports]: AccessControlResourceType.Export,

    // Early access features
    [Scene.EarlyAccessFeature]: AccessControlResourceType.EarlyAccessFeature,
    [Scene.EarlyAccessFeatures]: AccessControlResourceType.EarlyAccessFeature,

    // Customer analytics (only journey scenes — configuration uses project-level admin)
    [Scene.CustomerJourneyBuilder]: AccessControlResourceType.CustomerAnalytics,
    [Scene.CustomerJourneyTemplates]: AccessControlResourceType.CustomerAnalytics,

    // AI observability
    [Scene.AIObservability]: AccessControlResourceType.LlmAnalytics,
    [Scene.AIObservabilityDataset]: AccessControlResourceType.LlmAnalytics,
    [Scene.AIObservabilityDatasets]: AccessControlResourceType.LlmAnalytics,
    [Scene.AIObservabilityEvaluation]: AccessControlResourceType.LlmAnalytics,
    [Scene.AIObservabilityEvaluations]: AccessControlResourceType.LlmAnalytics,
    [Scene.AIObservabilityPlayground]: AccessControlResourceType.LlmAnalytics,
    [Scene.AIObservabilityTrace]: AccessControlResourceType.LlmAnalytics,
    [Scene.AIObservabilityUsers]: AccessControlResourceType.LlmAnalytics,

    // Data warehouse sources - not included here because self-managed sources don't have access control.
    // Managed sources handle access control at the logic level via SIDE_PANEL_CONTEXT_KEY.
}
