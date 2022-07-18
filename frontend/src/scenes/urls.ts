import { DashboardType, FilterType, InsightShortId } from '~/types'
import { combineUrl } from 'kea-router'
import { ExportOptions } from '~/exporter/types'

/**
 * To add a new URL to the front end:
 * - add a URL function here
 * - add a scene to the enum in sceneTypes.ts
 * - add a scene configuration in scenes.ts
 * - add a route to scene mapping in scenes.ts
 * - and add a scene import in appScenes.ts
 *
 * Sync the paths with AutoProjectMiddleware!
 */
export const urls = {
    default: (): string => '/',
    dashboards: (): string => '/dashboard',
    dashboard: (id: string | number, highlightInsightId?: string): string =>
        combineUrl(`/dashboard/${id}`, highlightInsightId ? { highlightInsightId } : {}).url,
    dashboardSharing: (id: string | number): string => `/dashboard/${id}/sharing`,
    dashboardSubcriptions: (id: string | number): string => `/dashboard/${id}/subscriptions`,
    dashboardSubcription: (id: string | number, subscriptionId: string): string =>
        `/dashboard/${id}/subscriptions/${subscriptionId}`,

    sharedDashboard: (shareToken: string): string => `/shared_dashboard/${shareToken}`,
    createAction: (): string => `/data-management/actions/new`,
    action: (id: string | number): string => `/data-management/actions/${id}`,
    actions: (): string => '/data-management/actions',
    eventDefinitions: (): string => '/data-management/events',
    eventDefinition: (id: string | number): string => `/data-management/events/${id}`,
    eventPropertyDefinitions: (): string => '/data-management/event-properties',
    eventPropertyDefinition: (id: string | number): string => `/data-management/event-properties/${id}`,
    events: (): string => '/events',
    insightNew: (filters?: Partial<FilterType>, dashboardId?: DashboardType['id'] | null): string =>
        combineUrl('/insights/new', dashboardId ? { dashboard: dashboardId } : {}, filters ? { filters } : {}).url,
    insightEdit: (id: InsightShortId): string => `/insights/${id}/edit`,
    insightView: (id: InsightShortId): string => `/insights/${id}`,
    insightSubcriptions: (id: InsightShortId): string => `/insights/${id}/subscriptions`,
    insightSubcription: (id: InsightShortId, subscriptionId: string): string =>
        `/insights/${id}/subscriptions/${subscriptionId}`,
    insightSharing: (id: InsightShortId): string => `/insights/${id}/sharing`,
    savedInsights: (): string => '/insights',
    webPerformance: (): string => '/web-performance',
    webPerformanceWaterfall: (id: string): string => `/web-performance/${id}/waterfall`,
    sessionRecordings: (): string => '/recordings',
    person: (id: string, encode: boolean = true): string =>
        encode ? `/person/${encodeURIComponent(id)}` : `/person/${id}`,
    persons: (): string => '/persons',
    groups: (groupTypeIndex: string): string => `/groups/${groupTypeIndex}`,
    // :TRICKY: Note that groupKey is provided by user. We need to override urlPatternOptions for kea-router.
    group: (groupTypeIndex: string | number, groupKey: string, encode: boolean = true): string =>
        `/groups/${groupTypeIndex}/${encode ? encodeURIComponent(groupKey) : groupKey}`,
    cohort: (id: string | number): string => `/cohorts/${id}`,
    cohorts: (): string => '/cohorts',
    experiment: (id: string | number): string => `/experiments/${id}`,
    experiments: (): string => '/experiments',
    featureFlags: (): string => '/feature_flags',
    featureFlag: (id: string | number): string => `/feature_flags/${id}`,
    annotations: (): string => '/annotations',
    projectApps: (): string => '/project/apps',
    frontendApp: (id: string | number): string => `/app/${id}`,
    projectCreateFirst: (): string => '/project/create',
    projectHomepage: (): string => '/home',
    projectSettings: (): string => '/project/settings',
    mySettings: (): string => '/me/settings',
    organizationSettings: (): string => '/organization/settings',
    organizationCreationConfirm: (): string => '/organization/confirm-creation',
    organizationCreateFirst: (): string => '/organization/create',
    toolbarLaunch: (): string => '/toolbar',
    // Onboarding / setup routes
    login: (): string => '/login',
    passwordReset: (): string => '/reset',
    passwordResetComplete: (userUuid: string, token: string): string => `/reset/${userUuid}/${token}`,
    preflight: (): string => '/preflight',
    signup: (): string => '/signup',
    inviteSignup: (id: string): string => `/signup/${id}`,
    ingestion: (): string => '/ingestion',
    // Cloud only
    organizationBilling: (): string => '/organization/billing',
    billingSubscribed: (): string => '/organization/billing/subscribed',
    // Self-hosted only
    instanceLicenses: (): string => '/instance/licenses',
    instanceStatus: (): string => '/instance/status',
    instanceStaffUsers: (): string => '/instance/staff_users',
    instanceKafkaInspector: (): string => '/instance/kafka_inspector',
    instanceSettings: (): string => '/instance/settings',
    instanceMetrics: (): string => `/instance/metrics`,
    asyncMigrations: (): string => '/instance/async_migrations',
    deadLetterQueue: (): string => '/instance/dead_letter_queue',
    unsubscribe: (): string => '/unsubscribe',
    integrationsRedirect: (kind: string): string => `/integrations/${kind}/redirect`,
    shared: (token: string, exportOptions?: ExportOptions): string =>
        combineUrl(`/shared/${token}`, {
            ...(exportOptions?.whitelabel ? { whitelabel: null } : {}),
            ...(exportOptions?.legend ? { legend: null } : {}),
            ...(exportOptions?.noHeader ? { legend: null } : {}),
        }).url,
    embedded: (token: string, exportOptions?: ExportOptions): string =>
        combineUrl(`/embedded/${token}`, {
            ...(exportOptions?.whitelabel ? { whitelabel: null } : {}),
            ...(exportOptions?.legend ? { legend: null } : {}),
            ...(exportOptions?.noHeader ? { noHeader: null } : {}),
        }).url,
}
