import { combineUrl } from 'kea-router'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import type { ExportOptions } from '~/exporter/types'
import { productUrls } from '~/products'
import { ActivityTab, AnnotationType, PipelineNodeTab, PipelineStage, PipelineTab, ProductKey, SDKKey } from '~/types'

import type { BillingSectionId } from './billing/types'
import type { OnboardingStepKey } from './onboarding/onboardingLogic'
import type { SettingId, SettingLevelId, SettingSectionId } from './settings/types'

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
    ...productUrls,
    absolute: (path = ''): string => window.location.origin + path,
    default: (): string => '/',
    project: (id: string | number, path = ''): string => `/project/${id}` + path,
    currentProject: (path = ''): string => urls.project(getCurrentTeamId(), path),
    eventDefinitions: (): string => '/data-management/events',
    eventDefinition: (id: string | number): string => `/data-management/events/${id}`,
    eventDefinitionEdit: (id: string | number): string => `/data-management/events/${id}/edit`,
    propertyDefinitions: (type?: string): string => combineUrl('/data-management/properties', type ? { type } : {}).url,
    propertyDefinition: (id: string | number): string => `/data-management/properties/${id}`,
    propertyDefinitionEdit: (id: string | number): string => `/data-management/properties/${id}/edit`,
    dataManagementHistory: (): string => '/data-management/history',
    database: (): string => '/data-management/database',
    activity: (tab: ActivityTab | ':tab' = ActivityTab.ExploreEvents): string => `/activity/${tab}`,
    event: (id: string, timestamp: string): string =>
        `/events/${encodeURIComponent(id)}/${encodeURIComponent(timestamp)}`,
    ingestionWarnings: (): string => '/data-management/ingestion-warnings',
    revenueSettings: (): string => '/data-management/revenue',

    pipelineNodeNew: (
        stage: PipelineStage | ':stage',
        { id, kind }: { id?: string | number; kind?: string } = {}
    ): string => {
        let base = `/pipeline/new/${stage}`
        if (id) {
            base += `/${id}`
        }

        if (kind) {
            return `${base}?kind=${kind}`
        }

        return base
    },
    pipeline: (tab?: PipelineTab | ':tab'): string => `/pipeline/${tab ? tab : PipelineTab.Overview}`,
    /** @param id 'new' for new, uuid for batch exports and numbers for plugins */
    pipelineNode: (
        stage: PipelineStage | ':stage',
        id: string | number,
        nodeTab?: PipelineNodeTab | ':nodeTab'
    ): string =>
        `/pipeline/${!stage.startsWith(':') && !stage?.endsWith('s') ? `${stage}s` : stage}/${id}${
            nodeTab ? `/${nodeTab}` : ''
        }`,
    errorTracking: (params = {}): string => combineUrl('/error_tracking', params).url,
    errorTrackingConfiguration: (): string => '/error_tracking/configuration',
    /** @param id A UUID or 'new'. ':id' for routing. */
    errorTrackingIssue: (id: string, fingerprint?: string): string =>
        combineUrl(`/error_tracking/${id}`, { fingerprint }).url,
    customCss: (): string => '/themes/custom-css',
    sqlEditor: (query?: string, view_id?: string, insightShortId?: string): string => {
        if (query) {
            return `/sql?open_query=${encodeURIComponent(query)}`
        }

        if (view_id) {
            return `/sql?open_view=${view_id}`
        }

        if (insightShortId) {
            return `/sql?open_insight=${insightShortId}`
        }

        return '/sql'
    },
    annotations: (): string => '/data-management/annotations',
    annotation: (id: AnnotationType['id'] | ':id'): string => `/data-management/annotations/${id}`,
    organizationCreateFirst: (): string => '/create-organization',
    projectCreateFirst: (): string => '/organization/create-project',
    projectHomepage: (): string => '/',
    max: (): string => '/max',
    settings: (section: SettingSectionId | SettingLevelId = 'project', setting?: SettingId): string =>
        combineUrl(`/settings/${section}`, undefined, setting).url,
    organizationCreationConfirm: (): string => '/organization/confirm-creation',
    toolbarLaunch: (): string => '/toolbar',
    site: (url: string): string => `/site/${url === ':url' ? url : encodeURIComponent(url)}`,
    // Onboarding / setup routes
    login: (): string => '/login',
    login2FA: (): string => '/login/2fa',
    login2FASetup: (): string => '/login/2fa_setup',
    passwordReset: (): string => '/reset',
    passwordResetComplete: (userUuid: string, token: string): string => `/reset/${userUuid}/${token}`,
    preflight: (): string => '/preflight',
    signup: (): string => '/signup',
    verifyEmail: (userUuid: string = '', token: string = ''): string =>
        `/verify_email${userUuid ? `/${userUuid}` : ''}${token ? `/${token}` : ''}`,
    inviteSignup: (id: string): string => `/signup/${id}`,
    products: (): string => '/products',
    onboarding: (productKey: string, stepKey?: OnboardingStepKey, sdk?: SDKKey): string =>
        `/onboarding/${productKey}${stepKey ? '?step=' + stepKey : ''}${
            sdk && stepKey ? '&sdk=' + sdk : sdk ? '?sdk=' + sdk : ''
        }`,
    // Cloud only
    organizationBilling: (products?: ProductKey[]): string =>
        `/organization/billing${products && products.length ? `?products=${products.join(',')}` : ''}`,
    organizationBillingSection: (section: BillingSectionId = 'overview'): string =>
        combineUrl(`/organization/billing/${section}`).url,
    billingAuthorizationStatus: (): string => `/billing/authorization_status`,
    // Self-hosted only
    instanceStatus: (): string => '/instance/status',
    instanceStaffUsers: (): string => '/instance/staff_users',
    instanceKafkaInspector: (): string => '/instance/kafka_inspector',
    instanceSettings: (): string => '/instance/settings',
    instanceMetrics: (): string => `/instance/metrics`,
    asyncMigrations: (): string => '/instance/async_migrations',
    asyncMigrationsFuture: (): string => '/instance/async_migrations/future',
    asyncMigrationsSettings: (): string => '/instance/async_migrations/settings',
    deadLetterQueue: (): string => '/instance/dead_letter_queue',
    unsubscribe: (): string => '/unsubscribe',
    integrationsRedirect: (kind: string): string => `/integrations/${kind}/callback`,
    shared: (token: string, exportOptions: ExportOptions = {}): string =>
        combineUrl(
            `/shared/${token}`,
            Object.entries(exportOptions)
                .filter((x) => x[1])
                .reduce(
                    (acc, [key, val]) => ({
                        ...acc,
                        [key]: val === true ? null : val,
                    }),
                    {}
                )
        ).url,
    embedded: (token: string, exportOptions?: ExportOptions): string =>
        urls.shared(token, exportOptions).replace('/shared/', '/embedded/'),
    debugQuery: (query?: string | Record<string, any>): string =>
        combineUrl('/debug', {}, query ? { q: typeof query === 'string' ? query : JSON.stringify(query) } : {}).url,
    debugHog: (): string => '/debug/hog',
    feedback: (): string => '/feedback',
    issues: (): string => '/issues',
    moveToPostHogCloud: (): string => '/move-to-cloud',
    heatmaps: (params?: string): string =>
        `/heatmaps${params ? `?${params.startsWith('?') ? params.slice(1) : params}` : ''}`,
    links: (params?: string): string =>
        `/links${params ? `?${params.startsWith('?') ? params.slice(1) : params}` : ''}`,
    link: (id: string): string => `/link/${id}`,
    sessionAttributionExplorer: (): string => '/web/session-attribution-explorer',
    wizard: (): string => `/wizard`,
    startups: (ycProgram?: boolean): string => `/startups${ycProgram ? '/yc' : ''}`,
    hogFunction: (id: string): string => `/functions/${id}`,
    hogFunctionNew: (templateId: string): string => `/functions/new/${templateId}`,
    errorTrackingAlert: (id: string): string => `/error_tracking/alerts/${id}`,
    errorTrackingAlertNew: (templateId: string): string => `/error_tracking/alerts/new/${templateId}`,
    chat: (id: string): string => `/chat/${id}`,
    chatList: (): string => `/chat`,
}
