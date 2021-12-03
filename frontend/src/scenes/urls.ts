/* eslint-disable @typescript-eslint/explicit-module-boundary-types */
import { FilterType, InsightShortId } from '~/types'
import { combineUrl } from 'kea-router'

export const urls = {
    default: () => '/',
    notFound: () => '404',
    dashboards: () => '/dashboard',
    dashboard: (id: string | number) => `/dashboard/${id}`,
    createAction: () => `/action`, // TODO: For consistency, this should be `/action/new`
    action: (id: string | number) => `/action/${id}`,
    actions: () => '/events/actions',
    eventStats: () => '/events/stats',
    eventPropertyStats: () => '/events/properties',
    events: () => '/events',
    insightNew: (filters?: Partial<FilterType>) => `/insights/new${filters ? combineUrl('', filters).search : ''}`,
    insightRouter: (id: string) => `/i/${id}`,
    insightEdit: (id: InsightShortId, filters?: Partial<FilterType>) =>
        `/insights/${id}/edit${filters ? combineUrl('', filters).search : ''}`,
    insightView: (id: InsightShortId, filters?: Partial<FilterType>) =>
        `/insights/${id}${filters ? combineUrl('', filters).search : ''}`,
    savedInsights: () => '/insights',
    sessionRecordings: () => '/recordings',
    person: (id: string, encode: boolean = true) => (encode ? `/person/${encodeURIComponent(id)}` : `/person/${id}`),
    persons: () => '/persons',
    groups: (groupTypeIndex: string) => `/groups/${groupTypeIndex}`,
    group: (groupTypeIndex: string | number, groupKey: string, encode: boolean = true) =>
        `/groups/${groupTypeIndex}/${encode ? encodeURIComponent(groupKey) : groupKey}`,
    cohort: (id: string | number) => `/cohorts/${id}`,
    cohorts: () => '/cohorts',
    experiments: () => '/experiments',
    featureFlags: () => '/feature_flags',
    featureFlag: (id: string | number) => `/feature_flags/${id}`,
    annotations: () => '/annotations',
    plugins: () => '/project/plugins',
    projectCreateFirst: () => '/project/create',
    projectSettings: () => '/project/settings',
    mySettings: () => '/me/settings',
    organizationSettings: () => '/organization/settings',
    organizationCreateFirst: () => '/organization/create',
    // Onboarding / setup routes
    login: () => '/login',
    passwordReset: () => '/reset',
    passwordResetComplete: (userUuid: string, token: string) => `/reset/${userUuid}/${token}`,
    preflight: () => '/preflight',
    signup: () => '/signup',
    inviteSignup: (id: string) => `/signup/${id}`,
    personalization: () => '/personalization',
    ingestion: () => '/ingestion',
    onboardingSetup: () => '/setup',
    // Cloud only
    organizationBilling: () => '/organization/billing',
    billingSubscribed: () => '/organization/billing/subscribed',
    // Self-hosted only
    instanceLicenses: () => '/instance/licenses',
    systemStatus: () => '/instance/status',
    systemStatusPage: (page: string) => `/instance/status/${page}`,
}
