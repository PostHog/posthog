import { combineUrl } from 'kea-router'
import { getCurrentTeamId } from 'lib/utils/getAppContext'

import { ExportOptions } from '~/exporter/types'
import { DashboardFilter, HogQLFilters, Node } from '~/queries/schema'
import {
    ActionType,
    ActivityTab,
    AnnotationType,
    DashboardType,
    InsightShortId,
    InsightType,
    PipelineNodeTab,
    PipelineStage,
    PipelineTab,
    ProductKey,
    RecordingUniversalFilters,
    ReplayTabs,
    SDKKey,
} from '~/types'

import { OnboardingStepKey } from './onboarding/onboardingLogic'
import { SettingId, SettingLevelId, SettingSectionId } from './settings/types'
import { SurveysTabs } from './surveys/surveysLogic'

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
    absolute: (path = ''): string => window.location.origin + path,
    default: (): string => '/',
    project: (id: string | number, path = ''): string => `/project/${id}` + path,
    currentProject: (path = ''): string => urls.project(getCurrentTeamId(), path),
    dashboards: (): string => '/dashboard',
    dashboard: (id: string | number, highlightInsightId?: string): string =>
        combineUrl(`/dashboard/${id}`, highlightInsightId ? { highlightInsightId } : {}).url,
    dashboardTextTile: (id: string | number, textTileId: string | number): string =>
        `${urls.dashboard(id)}/text-tiles/${textTileId}`,
    dashboardSharing: (id: string | number): string => `/dashboard/${id}/sharing`,
    dashboardSubcriptions: (id: string | number): string => `/dashboard/${id}/subscriptions`,
    dashboardSubcription: (id: string | number, subscriptionId: string): string =>
        `/dashboard/${id}/subscriptions/${subscriptionId}`,

    sharedDashboard: (shareToken: string): string => `/shared_dashboard/${shareToken}`,
    createAction: (): string => `/data-management/actions/new`,
    duplicateAction: (action: ActionType | null): string => {
        const queryParams = action ? `?copy=${encodeURIComponent(JSON.stringify(action))}` : ''
        return `/data-management/actions/new/${queryParams}`
    },
    action: (id: string | number): string => `/data-management/actions/${id}`,
    actions: (): string => '/data-management/actions',
    eventDefinitions: (): string => '/data-management/events',
    eventDefinition: (id: string | number): string => `/data-management/events/${id}`,
    eventDefinitionEdit: (id: string | number): string => `/data-management/events/${id}/edit`,
    propertyDefinitions: (type?: string): string => combineUrl('/data-management/properties', type ? { type } : {}).url,
    propertyDefinition: (id: string | number): string => `/data-management/properties/${id}`,
    propertyDefinitionEdit: (id: string | number): string => `/data-management/properties/${id}/edit`,
    dataManagementHistory: (): string => '/data-management/history',
    database: (): string => '/data-management/database',
    activity: (tab: ActivityTab | ':tab' = ActivityTab.ExploreEvents): string => `/activity/${tab}`,
    /** @deprecated in favor of /activity */
    events: (): string => `/events`,
    event: (id: string, timestamp: string): string =>
        `/events/${encodeURIComponent(id)}/${encodeURIComponent(timestamp)}`,
    ingestionWarnings: (): string => '/data-management/ingestion-warnings',
    insights: (): string => '/insights',
    insightNew: (type?: InsightType, dashboardId?: DashboardType['id'] | null, query?: Node): string =>
        combineUrl('/insights/new', dashboardId ? { dashboard: dashboardId } : {}, {
            ...(type ? { insight: type } : {}),
            ...(query ? { q: typeof query === 'string' ? query : JSON.stringify(query) } : {}),
        }).url,
    insightNewHogQL: (query: string, filters?: HogQLFilters): string =>
        combineUrl(
            `/data-warehouse`,
            {},
            {
                q: JSON.stringify({
                    kind: 'DataTableNode',
                    full: true,
                    source: { kind: 'HogQLQuery', query, filters },
                }),
            }
        ).url,
    insightEdit: (id: InsightShortId): string => `/insights/${id}/edit`,
    insightView: (id: InsightShortId, filtersOverride?: DashboardFilter): string =>
        `/insights/${id}${filtersOverride !== undefined ? `?filters_override=${JSON.stringify(filtersOverride)}` : ''}`,
    insightSubcriptions: (id: InsightShortId): string => `/insights/${id}/subscriptions`,
    insightSubcription: (id: InsightShortId, subscriptionId: string): string =>
        `/insights/${id}/subscriptions/${subscriptionId}`,
    insightSharing: (id: InsightShortId): string => `/insights/${id}/sharing`,
    savedInsights: (tab?: string): string => `/insights${tab ? `?tab=${tab}` : ''}`,
    webAnalytics: (): string => `/web`,

    replay: (tab?: ReplayTabs, filters?: Partial<RecordingUniversalFilters>, sessionRecordingId?: string): string =>
        combineUrl(tab ? `/replay/${tab}` : '/replay/home', {
            ...(filters ? { filters } : {}),
            ...(sessionRecordingId ? { sessionRecordingId } : {}),
        }).url,
    replayPlaylist: (id: string): string => `/replay/playlists/${id}`,
    replaySingle: (id: string): string => `/replay/${id}`,
    replayFilePlayback: (): string => '/replay/file-playback',

    personByDistinctId: (id: string, encode: boolean = true): string =>
        encode ? `/person/${encodeURIComponent(id)}` : `/person/${id}`,
    personByUUID: (uuid: string, encode: boolean = true): string =>
        encode ? `/persons/${encodeURIComponent(uuid)}` : `/persons/${uuid}`,
    persons: (): string => '/persons',
    pipelineNodeNew: (stage: PipelineStage | ':stage', id?: string | number): string => {
        return `/pipeline/new/${stage}${id ? `/${id}` : ''}`
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
    groups: (groupTypeIndex: string | number): string => `/groups/${groupTypeIndex}`,
    // :TRICKY: Note that groupKey is provided by user. We need to override urlPatternOptions for kea-router.
    group: (groupTypeIndex: string | number, groupKey: string, encode: boolean = true, tab?: string | null): string =>
        `/groups/${groupTypeIndex}/${encode ? encodeURIComponent(groupKey) : groupKey}${tab ? `/${tab}` : ''}`,
    cohort: (id: string | number): string => `/cohorts/${id}`,
    cohorts: (): string => '/cohorts',
    experiment: (id: string | number): string => `/experiments/${id}`,
    experiments: (): string => '/experiments',
    featureFlags: (tab?: string): string => `/feature_flags${tab ? `?tab=${tab}` : ''}`,
    featureFlag: (id: string | number): string => `/feature_flags/${id}`,
    earlyAccessFeatures: (): string => '/early_access_features',
    /** @param id A UUID or 'new'. ':id' for routing. */
    earlyAccessFeature: (id: string): string => `/early_access_features/${id}`,
    errorTracking: (): string => '/error_tracking',
    errorTrackingGroup: (fingerprint: string): string =>
        `/error_tracking/${fingerprint === ':fingerprint' ? fingerprint : encodeURIComponent(fingerprint)}`,
    surveys: (tab?: SurveysTabs): string => `/surveys${tab ? `?tab=${tab}` : ''}`,
    /** @param id A UUID or 'new'. ':id' for routing. */
    survey: (id: string): string => `/surveys/${id}`,
    surveyTemplates: (): string => '/survey_templates',
    dataWarehouse: (query?: string | Record<string, any>): string =>
        combineUrl(`/data-warehouse`, {}, query ? { q: typeof query === 'string' ? query : JSON.stringify(query) } : {})
            .url,
    dataWarehouseView: (id: string): string => combineUrl(`/data-warehouse/view/${id}`).url,
    dataWarehouseTable: (): string => `/data-warehouse/new`,
    dataWarehouseRedirect: (kind: string): string => `/data-warehouse/${kind}/redirect`,
    annotations: (): string => '/data-management/annotations',
    annotation: (id: AnnotationType['id'] | ':id'): string => `/data-management/annotations/${id}`,
    organizationCreateFirst: (): string => '/create-organization',
    projectCreateFirst: (): string => '/organization/create-project',
    projectHomepage: (): string => '/',
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
    feedback: (): string => '/feedback',
    issues: (): string => '/issues',
    notebooks: (): string => '/notebooks',
    notebook: (shortId: string): string => `/notebooks/${shortId}`,
    canvas: (): string => `/canvas`,
    moveToPostHogCloud: (): string => '/move-to-cloud',
    heatmaps: (params?: string): string =>
        `/heatmaps${params ? `?${params.startsWith('?') ? params.slice(1) : params}` : ''}`,
    alert: (id: InsightShortId, alertId: string): string => `/insights/${id}/alerts/${alertId}`,
    alerts: (id: InsightShortId): string => `/insights/${id}/alerts`,
    sessionAttributionExplorer: (): string => '/web/session-attribution-explorer',
}
