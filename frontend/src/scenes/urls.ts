import { combineUrl } from 'kea-router'

import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { productUrls } from '~/products'
import { SharingConfigurationSettings } from '~/queries/schema/schema-general'
import { ActivityTab, AnnotationType, CommentType, OnboardingStepKey, ProductKey, SDKKey } from '~/types'

import type { BillingSectionId } from './billing/types'
import { DataPipelinesNewSceneKind } from './data-pipelines/DataPipelinesNewScene'
import type { DataPipelinesSceneTab } from './data-pipelines/DataPipelinesScene'
import { OutputTab } from './data-warehouse/editor/outputPaneLogic'
import type { DataWarehouseSourceSceneTab } from './data-warehouse/settings/DataWarehouseSourceScene'
import type { HogFunctionSceneTab } from './hog-functions/HogFunctionScene'
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
    newTab: () => '/new',
    eventDefinitions: (): string => '/data-management/events',
    eventDefinition: (id: string | number): string => `/data-management/events/${id}`,
    eventDefinitionEdit: (id: string | number): string => `/data-management/events/${id}/edit`,
    propertyDefinitions: (type?: string): string => combineUrl('/data-management/properties', type ? { type } : {}).url,
    propertyDefinition: (id: string | number): string => `/data-management/properties/${id}`,
    propertyDefinitionEdit: (id: string | number): string => `/data-management/properties/${id}/edit`,
    schemaManagement: (): string => '/data-management/schema',
    dataManagementHistory: (): string => '/data-management/history',
    database: (): string => '/data-management/database',
    dataWarehouseManagedViewsets: (): string => '/data-management/managed-viewsets',
    activity: (tab: ActivityTab | ':tab' = ActivityTab.ExploreEvents): string => `/activity/${tab}`,
    event: (id: string, timestamp: string): string =>
        `/events/${encodeURIComponent(id)}/${encodeURIComponent(timestamp)}`,
    ingestionWarnings: (): string => '/data-management/ingestion-warnings',
    revenueSettings: (): string => '/data-management/revenue',
    marketingAnalytics: (): string => '/data-management/marketing-analytics',
    customCss: (): string => '/themes/custom-css',
    sqlEditor: (
        query?: string,
        view_id?: string,
        insightShortId?: string,
        draftId?: string,
        outputTab?: OutputTab
    ): string => {
        const params = new URLSearchParams()

        if (query) {
            params.set('open_query', query)
        } else if (view_id) {
            params.set('open_view', view_id)
        } else if (insightShortId) {
            params.set('open_insight', insightShortId)
        } else if (draftId) {
            params.set('open_draft', draftId)
        }

        if (outputTab) {
            params.set('output_tab', outputTab)
        }

        const queryString = params.toString()
        return `/sql${queryString ? `?${queryString}` : ''}`
    },
    annotations: (): string => '/data-management/annotations',
    annotation: (id: AnnotationType['id'] | ':id'): string => `/data-management/annotations/${id}`,
    comments: (): string => '/data-management/comments',
    comment: (id: CommentType['id'] | ':id'): string => `/data-management/comments/${id}`,
    organizationCreateFirst: (): string => '/create-organization',
    projectCreateFirst: (): string => '/organization/create-project',
    projectHomepage: (): string => '/',
    max: (chat?: string, ask?: string): string => combineUrl('/max', { ask, chat }).url,
    maxHistory: (): string => '/max/history',
    settings: (section: SettingSectionId | SettingLevelId = 'project', setting?: SettingId): string =>
        combineUrl(`/settings/${section}`, undefined, setting).url,
    organizationCreationConfirm: (): string => '/organization/confirm-creation',
    toolbarLaunch: (): string => '/toolbar',
    site: (url: string): string => `/site/${url === ':url' ? url : encodeURIComponent(url)}`,
    // Onboarding / setup routes
    login: (): string => '/login',
    login2FA: (): string => '/login/2fa',
    login2FASetup: (): string => '/login/2fa_setup',
    emailMFAVerify: (): string => '/login/verify',
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
    advancedActivityLogs: (): string => '/activity-logs',
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
    shared: (token: string, exportOptions: SharingConfigurationSettings = {}): string =>
        combineUrl(
            `/shared/${token}`,
            Object.entries(exportOptions)
                // strip falsey values
                .filter((x) => x[1])
                .reduce(
                    (acc, [key, val]) =>
                        Object.assign(acc, {
                            // just sends the key and not a value
                            // e.g., &showInspector not &showInspector=true
                            [key]: val === true ? null : val,
                        }),
                    {}
                )
        ).url,
    embedded: (token: string, exportOptions?: SharingConfigurationSettings): string =>
        urls.shared(token, exportOptions).replace('/shared/', '/embedded/'),
    debugQuery: (query?: string | Record<string, any>): string =>
        combineUrl('/debug', {}, query ? { q: typeof query === 'string' ? query : JSON.stringify(query) } : {}).url,
    debugHog: (): string => '/debug/hog',
    moveToPostHogCloud: (): string => '/move-to-cloud',
    heatmaps: (params?: string): string =>
        `/heatmaps${params ? `?${params.startsWith('?') ? params.slice(1) : params}` : ''}`,
    links: (params?: string): string =>
        `/links${params ? `?${params.startsWith('?') ? params.slice(1) : params}` : ''}`,
    link: (id: string): string => `/link/${id}`,
    sessionAttributionExplorer: (): string => '/web/session-attribution-explorer',
    wizard: (): string => `/wizard`,
    startups: (referrer?: string): string => `/startups${referrer ? `/${referrer}` : ''}`,
    oauthAuthorize: (): string => '/oauth/authorize',
    dataPipelines: (kind: DataPipelinesSceneTab = 'overview'): string => `/pipeline/${kind}`,
    dataPipelinesNew: (kind?: DataPipelinesNewSceneKind): string => `/pipeline/new/${kind ?? ''}`,
    dataWarehouseSource: (id: string, tab?: DataWarehouseSourceSceneTab): string =>
        `/data-warehouse/sources/${id}/${tab ?? 'schemas'}`,
    dataWarehouseSourceNew: (kind?: string): string => `/data-warehouse/new-source${kind ? `?kind=${kind}` : ''}`,
    batchExportNew: (service: string): string => `/pipeline/batch-exports/new/${service}`,
    batchExport: (id: string): string => `/pipeline/batch-exports/${id}`,
    legacyPlugin: (id: string): string => `/pipeline/plugins/${id}`,
    hogFunction: (id: string, tab?: HogFunctionSceneTab): string => `/functions/${id}${tab ? `?tab=${tab}` : ''}`,
    hogFunctionNew: (templateId: string): string => `/functions/new/${templateId}`,
}
