/* eslint-disable @typescript-eslint/explicit-module-boundary-types */
import { DashboardType, FilterType, InsightShortId } from '~/types'
import { combineUrl } from 'kea-router'

/*
To add a new URL to the front end:
 - add a URL function here
 - add a scene to the enum in sceneTypes.ts
 - add a scene configuration in scenes.ts
 - add a route to scene mapping in scenes.ts
 - and add a scene import in appScenes.ts

   Sync the paths with AutoProjectMiddleware!
 */
export const urls = {
    default: () => '/',
    dashboards: () => '/dashboard',
    dashboard: (id: string | number, highlightInsightId?: string) =>
        combineUrl(`/dashboard/${id}`, highlightInsightId ? { highlightInsightId } : {}).url,
    sharedDashboard: (shareToken: string) => `/shared_dashboard/${shareToken}`,
    createAction: () => `/data-management/actions/new`, // TODO: For consistency, this should be `/action/new`
    action: (id: string | number) => `/data-management/actions/${id}`,
    actions: () => '/data-management/actions',
    eventDefinitions: () => '/data-management/events',
    eventDefinition: (id: string | number) => `/data-management/events/${id}`,
    eventPropertyDefinitions: () => '/data-management/event-properties',
    eventPropertyDefinition: (id: string | number) => `/data-management/event-properties/${id}`,
    events: () => '/events',
    insightNew: (filters?: Partial<FilterType>, dashboardId?: DashboardType['id'] | null) =>
        combineUrl('/insights/new', dashboardId ? { dashboard: dashboardId } : {}, filters ? { filters } : {}).url,
    insightEdit: (id: InsightShortId) => `/insights/${id}/edit`,
    insightView: (id: InsightShortId) => `/insights/${id}`,
    savedInsights: () => '/insights',
    webPerformance: () => '/web-performance',
    webPerformanceWaterfall: (id: string) => `/web-performance/${id}/waterfall`,
    sessionRecordings: () => '/recordings',
    person: (id: string, encode: boolean = true) => (encode ? `/person/${encodeURIComponent(id)}` : `/person/${id}`),
    persons: () => '/persons',
    groups: (groupTypeIndex: string) => `/groups/${groupTypeIndex}`,
    // :TRICKY: Note that groupKey is provided by user. We need to override urlPatternOptions for kea-router.
    group: (groupTypeIndex: string | number, groupKey: string, encode: boolean = true) =>
        `/groups/${groupTypeIndex}/${encode ? encodeURIComponent(groupKey) : groupKey}`,
    cohort: (id: string | number) => `/cohorts/${id}`,
    cohorts: () => '/cohorts',
    experiment: (id: string | number) => `/experiments/${id}`,
    experiments: () => '/experiments',
    featureFlags: () => '/feature_flags',
    featureFlag: (id: string | number) => `/feature_flags/${id}`,
    annotations: () => '/annotations',
    projectApps: () => '/project/apps',
    frontendApp: (id: string | number) => `/app/${id}`,
    projectCreateFirst: () => '/project/create',
    projectHomepage: () => '/home',
    projectSettings: () => '/project/settings',
    mySettings: () => '/me/settings',
    organizationSettings: () => '/organization/settings',
    organizationCreateFirst: () => '/organization/create',
    toolbarLaunch: () => '/toolbar',
    // Onboarding / setup routes
    login: () => '/login',
    passwordReset: () => '/reset',
    passwordResetComplete: (userUuid: string, token: string) => `/reset/${userUuid}/${token}`,
    preflight: () => '/preflight',
    signup: () => '/signup',
    inviteSignup: (id: string) => `/signup/${id}`,
    ingestion: () => '/ingestion',
    // Cloud only
    organizationBilling: () => '/organization/billing',
    billingSubscribed: () => '/organization/billing/subscribed',
    // Self-hosted only
    instanceLicenses: () => '/instance/licenses',
    instanceStatus: () => '/instance/status',
    instanceStaffUsers: () => '/instance/staff_users',
    instanceKafkaInspector: () => '/instance/kafka_inspector',
    instanceSettings: () => '/instance/settings',
    instanceMetrics: () => `/instance/metrics`,
    asyncMigrations: () => '/instance/async_migrations',
    deadLetterQueue: () => '/instance/dead_letter_queue',
}
