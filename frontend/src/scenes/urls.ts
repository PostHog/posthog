/* eslint-disable @typescript-eslint/explicit-module-boundary-types */
import { FilterType, ViewType } from '~/types'
import { encodeParams } from 'kea-router'

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
    insights: () => '/insights',
    newInsight: () => '/insights/new',
    newInsightType: (view?: ViewType) =>
        `/insights/new${view ? `?insight=${encodeURIComponent(String(view).toUpperCase())}` : ''}`,
    newInsightFilters: (filters?: Partial<FilterType>) => `/insights/new${filters ? encodeParams(filters, '?') : ''}`,
    viewInsight: (id: string | number, filters?: Partial<FilterType>) =>
        `/insights/${id}${filters ? encodeParams(filters, '?') : ''}`,
    editInsight: (id: string | number, filters?: Partial<FilterType>) =>
        `/insights/${id}/edit${filters ? encodeParams(filters, '?') : ''}`,
    insightRouter: (id: string) => `/i/${id}`,
    sessions: () => '/sessions',
    sessionRecordings: () => '/recordings',
    person: (id: string) => `/person/${id}`,
    persons: () => '/persons',
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
    organizationBilling: () => '/organization/billing',
    organizationCreateFirst: () => '/organization/create',
    instanceLicenses: () => '/instance/licenses',
    systemStatus: () => '/instance/status',
    systemStatusPage: (page: string) => `/instance/status/${page}`,
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
}
