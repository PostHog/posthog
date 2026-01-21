import { combineUrl } from 'kea-router'

import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { fileSystemTypes, productUrls } from '~/products'
import { ProductKey, SharingConfigurationSettings } from '~/queries/schema/schema-general'
import { ActivityTab, AnnotationType, CommentType, OnboardingStepKey, SDKKey } from '~/types'

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
    newTab: () => '/search',
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
    coreEvents: (): string => '/data-management/core-events',
    marketingAnalytics: (): string => '/data-management/marketing-analytics',
    marketingAnalyticsApp: (): string => '/marketing',
    customCss: (): string => '/themes/custom-css',
    sqlEditor: (
        query?: string,
        view_id?: string,
        insightShortId?: string,
        draftId?: string,
        outputTab?: OutputTab,
        endpointName?: string
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

        if (endpointName) {
            params.set('endpoint_name', endpointName)
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
    projectRoot: (): string => '/',
    projectHomepage: (): string => '/home',
    ai: (chat?: string, ask?: string): string => combineUrl('/ai', { ask, chat }).url,
    aiHistory: (): string => '/ai/history',
    settings: (section: SettingSectionId | SettingLevelId = 'project', setting?: SettingId): string =>
        combineUrl(`/settings/${section}`, undefined, setting).url,
    organizationCreationConfirm: (): string => '/organization/confirm-creation',
    toolbarLaunch: (): string => '/toolbar',
    site: (url: string): string => `/site/${url === ':url' ? url : encodeURIComponent(url)}`,
    // Onboarding / setup routes
    login: (): string => '/login',
    login2FA: (): string => '/login/2fa',
    login2FASetup: (): string => '/login/2fa_setup',
    cliAuthorize: (): string => '/cli/authorize',
    emailMFAVerify: (): string => '/login/verify',
    liveDebugger: (): string => '/live-debugger',
    passwordReset: (): string => '/reset',
    passwordResetComplete: (userUuid: string, token: string): string => `/reset/${userUuid}/${token}`,
    preflight: (): string => '/preflight',
    signup: (): string => '/signup',
    verifyEmail: (userUuid: string = '', token: string = ''): string =>
        `/verify_email${userUuid ? `/${userUuid}` : ''}${token ? `/${token}` : ''}`,
    vercelLinkError: (): string => '/integrations/vercel/link-error',
    inviteSignup: (id: string): string => `/signup/${id}`,
    onboarding: ({
        campaign,
        productKey,
        stepKey,
        sdk,
    }: {
        campaign?: string
        productKey?: string
        stepKey?: OnboardingStepKey
        sdk?: SDKKey
    } = {}): string => {
        if (campaign) {
            return `/onboarding/coupons/${campaign}`
        }

        const params = new URLSearchParams()
        if (stepKey) {
            params.set('step', stepKey)
        }
        if (sdk) {
            params.set('sdk', sdk)
        }

        const base = `/onboarding${productKey ? `/${productKey}` : ''}`
        const queryString = params.toString()
        return `${base}${queryString ? `?${queryString}` : ''}`
    },
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
    materializedColumns: (): string => '/data-management/materialized-columns',
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
    heatmapNew: (params?: string): string =>
        `/heatmaps/new${params ? `?${params.startsWith('?') ? params.slice(1) : params}` : ''}`,
    heatmapRecording: (params?: string): string =>
        `/heatmaps/recording${params ? `?${params.startsWith('?') ? params.slice(1) : params}` : ''}`,
    heatmap: (id: string | number): string => `/heatmaps/${id}`,
    links: (params?: string): string =>
        `/links${params ? `?${params.startsWith('?') ? params.slice(1) : params}` : ''}`,
    link: (id: string): string => `/link/${id}`,
    sessionAttributionExplorer: (): string => '/web/session-attribution-explorer',
    sessionProfile: (id: string): string => `/sessions/${id}`,
    wizard: (): string => `/wizard`,
    coupons: (campaign: string): string => `/coupons/${campaign}`,
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
    productTours: (): string => '/product_tours',
    productTour: (id: string, params?: string): string =>
        `/product_tours/${id}${params ? `?${params.startsWith('?') ? params.slice(1) : params}` : ''}`,
    organizationDeactivated: (): string => '/organization-deactivated',
    approvals: (): string => '/settings/organization-approvals#change-requests',
    approval: (id: string): string => `/approvals/${id}`,
}

export interface UrlMatcher {
    type?: string
    matchers: Record<string, UrlMatcher>
}

const rootMatcher: UrlMatcher = { matchers: {} }

for (const [type, { href }] of Object.entries(fileSystemTypes)) {
    if (typeof href !== 'function') {
        continue
    }

    const computed = href(':id') // e.g. "/insights/:id"
    const pathname = computed.split('?')[0]

    // Normalize and split: "/insights/:id" -> ["insights", ":id"]
    const parts = pathname
        .replace(/^\/+|\/+$/g, '') // trim leading/trailing slashes
        .split('/')
        .filter(Boolean)

    if (!parts.includes(':id')) {
        continue
    }

    let node = rootMatcher

    for (const part of parts) {
        if (!node.matchers[part]) {
            node.matchers[part] = { matchers: {} }
        }
        node = node.matchers[part]

        if (part === ':id') {
            node.type = type
        }
    }
}

export function urlToResource(url: string): { type: string; ref: string } | null {
    const pathname = url.split('?')[0]

    const parts = pathname
        .replace(/^\/+|\/+$/g, '')
        .split('/')
        .filter(Boolean)

    let node: UrlMatcher = rootMatcher
    let id: string | null = null

    for (const part of parts) {
        if (node.matchers[part]) {
            node = node.matchers[part]
            continue
        }
        if (node.matchers[':id']) {
            node = node.matchers[':id']
            id = part
            continue
        }
        return null
    }

    if (node.type && id !== null) {
        return { type: node.type, ref: id }
    }

    return null
}
