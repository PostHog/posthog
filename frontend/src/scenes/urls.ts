/* eslint-disable @typescript-eslint/explicit-module-boundary-types */
import { FilterType } from '~/types'
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
    insightEdit: (id: string | number, filters?: Partial<FilterType>) =>
        `/insights/${id}/edit${filters ? combineUrl('', filters).search : ''}`,
    insightView: (id: string | number, filters?: Partial<FilterType>) =>
        `/insights/${id}${filters ? combineUrl('', filters).search : ''}`,
    savedInsights: () => '/insights',
    sessions: () => '/sessions',
    sessionRecordings: () => '/recordings',
    person: (id: string) => `/person/${id}`,
    persons: () => '/persons',
    groups: (groupTypeIndex: string) => `/groups/${groupTypeIndex}`,
    cohort: (id: string | number) => `/cohorts/${id}`,
    cohorts: () => '/cohorts',
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
