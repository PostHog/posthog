import { LogicWrapper } from 'kea'

// The enum here has to match the first and only exported component of the scene.
// If so, we can preload the scene's required chunks in parallel with the scene itself.

export enum Scene {
    Error404 = '404',
    ErrorNetwork = '4xx',
    ErrorProjectUnavailable = 'ProjectUnavailable',
    Dashboards = 'Dashboards',
    Dashboard = 'Dashboard',
    Database = 'Database',
    Insight = 'Insight',
    WebAnalytics = 'WebAnalytics',
    Cohorts = 'Cohorts',
    Cohort = 'Cohort',
    Events = 'Events',
    DataManagement = 'DataManagement',
    EventDefinitions = 'EventDefinitionsTable',
    EventDefinition = 'EventDefinition',
    PropertyDefinitions = 'PropertyDefinitionsTable',
    PropertyDefinition = 'PropertyDefinition',
    DataManagementHistory = 'DataManagementHistory',
    IngestionWarnings = 'IngestionWarnings',
    Replay = 'Replay',
    ReplaySingle = 'ReplaySingle',
    ReplayPlaylist = 'ReplayPlaylist',
    Person = 'Person',
    Persons = 'Persons',
    Pipeline = 'Pipeline',
    Groups = 'Groups',
    Group = 'Group',
    Action = 'Action',
    Actions = 'ActionsTable',
    Experiments = 'Experiments',
    Experiment = 'Experiment',
    BatchExports = 'BatchExports',
    BatchExport = 'BatchExport',
    BatchExportEdit = 'BatchExportEdit',
    FeatureFlags = 'FeatureFlags',
    FeatureFlag = 'FeatureFlag',
    EarlyAccessFeatures = 'EarlyAccessFeatures',
    EarlyAccessFeature = 'EarlyAccessFeature',
    Surveys = 'Surveys',
    Survey = 'Survey',
    SurveyTemplates = 'SurveyTemplates',
    DataWarehouse = 'DataWarehouse',
    DataWarehousePosthog = 'DataWarehousePosthog',
    DataWarehouseExternal = 'DataWarehouseExternal',
    DataWarehouseSavedQueries = 'DataWarehouseSavedQueries',
    DataWarehouseTable = 'DataWarehouseTable',
    OrganizationSettings = 'OrganizationSettings',
    OrganizationCreateFirst = 'OrganizationCreate',
    ProjectHomepage = 'ProjectHomepage',
    ProjectSettings = 'ProjectSettings',
    ProjectCreateFirst = 'ProjectCreate',
    SystemStatus = 'SystemStatus',
    AsyncMigrations = 'AsyncMigrations',
    DeadLetterQueue = 'DeadLetterQueue',
    MySettings = 'MySettings',
    Annotations = 'Annotations',
    Billing = 'Billing',
    Apps = 'Apps',
    FrontendAppScene = 'FrontendAppScene',
    AppMetrics = 'AppMetrics',
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
    Ingestion = 'IngestionWizard',
    OrganizationCreationConfirm = 'OrganizationCreationConfirm',
    Unsubscribe = 'Unsubscribe',
    DebugQuery = 'DebugQuery',
    VerifyEmail = 'VerifyEmail',
    Feedback = 'Feedback',
    Notebooks = 'Notebooks',
    Notebook = 'Notebook',
    Canvas = 'Canvas',
    Products = 'Products',
    Onboarding = 'Onboarding',
}

export type SceneProps = Record<string, any>

export type SceneComponent = (params?: SceneProps) => JSX.Element | null

export interface SceneExport {
    /** component to render for this scene */
    component: SceneComponent
    /** logic to mount for this scene */
    logic?: LogicWrapper
    /** convert URL parameters from scenes.ts into logic props */
    paramsToProps?: (params: SceneParams) => SceneProps
    /** when was the scene last touched, unix timestamp for sortability */
    lastTouch?: number
}

export interface LoadedScene extends SceneExport {
    name: string
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
    layout?: 'app' | 'app-raw' | 'app-container' | 'plain'
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
}
