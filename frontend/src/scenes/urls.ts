/* eslint-disable @typescript-eslint/explicit-module-boundary-types */
import { FilterType, InsightShortId } from '~/types'
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
    dashboard: (id: string | number) => `/dashboard/${id}`,
    sharedDashboard: (shareToken: string) => `/shared_dashboard/${shareToken}`,
    createAction: () => `/action`, // TODO: For consistency, this should be `/action/new`
    action: (id: string | number) => `/action/${id}`,
    actions: () => '/events/actions',
    eventStats: () => '/events/stats',
    eventStat: (id: string | number) => `/events/stats/${id}`,
    eventPropertyStats: () => '/events/properties',
    eventPropertyStat: (id: string | number) => `/events/properties/${id}`,
    events: () => '/events',
    insightNew: (filters?: Partial<FilterType>) =>
        `/insights/new${filters ? combineUrl('', '', { filters }).hash : ''}`,
    insightRouter: (id: string) => `/i/${id}`,
    insightEdit: (id: InsightShortId, filters?: Partial<FilterType>) =>
        `/insights/${id}/edit${filters ? combineUrl('', '', { filters }).hash : ''}`,
    insightView: (id: InsightShortId, filters?: Partial<FilterType>) =>
        `/insights/${id}${filters ? combineUrl('', '', { filters }).hash : ''}`,
    savedInsights: () => '/insights',
    webPerformance: () => '/web-performance',
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
    plugins: () => '/project/plugins',
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
    instanceSettings: () => '/instance/settings',
    instanceMetrics: () => `/instance/metrics`,
    asyncMigrations: () => '/instance/async_migrations',
    deadLetterQueue: () => '/instance/dead_letter_queue',
}
