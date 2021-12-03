import { LogicWrapper } from 'kea'

// The enum here has to match the first and only exported component of the scene.
// If so, we can preload the scene's required chunks in parallel with the scene itself.
export enum Scene {
    Error404 = '404',
    ErrorNetwork = '4xx',
    ErrorProjectUnavailable = 'ProjectUnavailable',
    Dashboards = 'Dashboards',
    Dashboard = 'Dashboard',
    Insight = 'Insight',
    InsightRouter = 'InsightRouter',
    Cohorts = 'Cohorts',
    Events = 'Events',
    EventStats = 'EventsVolumeTable',
    EventPropertyStats = 'PropertiesVolumeTable',
    SessionRecordings = 'SessionsRecordings',
    Person = 'Person',
    Persons = 'Persons',
    Groups = 'Groups',
    Group = 'Group',
    Action = 'Action',
    Actions = 'ActionsTable',
    Experiments = 'Experiments',
    FeatureFlags = 'FeatureFlags',
    FeatureFlag = 'FeatureFlag',
    OrganizationSettings = 'OrganizationSettings',
    OrganizationCreateFirst = 'OrganizationCreate',
    ProjectSettings = 'ProjectSettings',
    ProjectCreateFirst = 'ProjectCreate',
    SystemStatus = 'SystemStatus',
    Licenses = 'Licenses',
    MySettings = 'MySettings',
    Annotations = 'Annotations',
    Billing = 'Billing',
    BillingSubscribed = 'BillingSubscribed',
    Plugins = 'Plugins',
    SavedInsights = 'SavedInsights',
    // Authentication & onboarding routes
    Login = 'Login',
    Signup = 'Signup',
    InviteSignup = 'InviteSignup',
    PasswordReset = 'PasswordReset',
    PasswordResetComplete = 'PasswordResetComplete',
    PreflightCheck = 'PreflightCheck',
    Ingestion = 'IngestionWizard',
    OnboardingSetup = 'OnboardingSetup',
    Personalization = 'Personalization',
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
    /** Hides most navigation UI, like the sidebar and breadcrumbs. */
    plain?: boolean
    /** Hides demo project warnings (DemoWarning.tsx) */
    hideDemoWarnings?: boolean
    /** Personal account management (used e.g. by breadcrumbs) */
    personal?: boolean
    /** Instance management (used e.g. by breadcrumbs) */
    instanceLevel?: boolean
    /** Route requires organization access (used e.g. by breadcrumbs) */
    organizationBased?: boolean
    /** Route requires project access (used e.g. by breadcrumbs). `true` implies `organizationBased` */
    projectBased?: boolean
}
