import { LogicWrapper } from 'kea'

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

export type SceneProps = Record<string, any>

export type SceneComponent = (params?: SceneProps) => JSX.Element | null

export interface SceneExport {
    /** component to render for this scene */
    component: SceneComponent
    /** logic to mount for this scene */
    logic?: LogicWrapper
    /** convert URL parameters from scenes.ts into logic props */
    paramsToProps?: (params: Record<string, string>) => SceneProps
}

export interface LoadedScene extends SceneExport {
    name: string
    params?: Record<string, any>
}

export interface Params {
    [param: string]: any
}

export interface SceneConfig {
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
