/* eslint @typescript-eslint/explicit-module-boundary-types: 0 */
// Generated by @posthog/esbuilder/utils.mjs, based on product folder manifests under products/*/manifest.tsx
// The imports are preserved between builds, so please update if any are missing or extra.

import {
    IconDashboard,
    IconGraph,
    IconMegaphone,
    IconNotebook,
    IconPerson,
    IconPieChart,
    IconRewindPlay,
    IconRocket,
    IconTestTube,
    IconToggle,
} from '@posthog/icons'
import { combineUrl } from 'kea-router'
import { AlertType } from 'lib/components/Alerts/types'
import { toParams } from 'lib/utils'
import { Params } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import {
    ExperimentFunnelsQuery,
    ExperimentTrendsQuery,
    HogQLFilters,
    HogQLVariable,
    Node,
} from '~/queries/schema/schema-general'

import { DashboardType, InsightShortId, InsightType, RecordingUniversalFilters, ReplayTabs } from './types'

/** This const is auto-generated, as is the whole file */
export const productScenes: Record<string, () => Promise<any>> = {
    EarlyAccessFeatures: () => import('../../products/early_access_features/frontend/EarlyAccessFeatures'),
    EarlyAccessFeature: () => import('../../products/early_access_features/frontend/EarlyAccessFeature'),
    LLMObservability: () => import('../../products/llm_observability/frontend/LLMObservabilityScene'),
    LLMObservabilityTrace: () => import('../../products/llm_observability/frontend/LLMObservabilityTraceScene'),
    LLMObservabilityUsers: () => import('../../products/llm_observability/frontend/LLMObservabilityUsers'),
    MessagingAutomations: () => import('../../products/messaging/frontend/Automations'),
    MessagingBroadcasts: () => import('../../products/messaging/frontend/Broadcasts'),
    MessagingProviders: () => import('../../products/messaging/frontend/Providers'),
    MessagingLibrary: () => import('../../products/messaging/frontend/Library'),
}

/** This const is auto-generated, as is the whole file */
export const productRoutes: Record<string, [string, string]> = {
    '/early_access_features': ['EarlyAccessFeatures', 'earlyAccessFeatures'],
    '/early_access_features/:id': ['EarlyAccessFeature', 'earlyAccessFeature'],
    '/llm-observability': ['LLMObservability', 'llmObservability'],
    '/llm-observability/dashboard': ['LLMObservability', 'llmObservabilityDashboard'],
    '/llm-observability/generations': ['LLMObservability', 'llmObservabilityGenerations'],
    '/llm-observability/traces': ['LLMObservability', 'llmObservabilityTraces'],
    '/llm-observability/traces/:id': ['LLMObservabilityTrace', 'llmObservability'],
    '/llm-observability/users': ['LLMObservability', 'llmObservabilityUsers'],
    '/messaging/automations': ['MessagingAutomations', 'messagingAutomations'],
    '/messaging/automations/:id': ['MessagingAutomations', 'messagingAutomation'],
    '/messaging/automations/new': ['MessagingAutomations', 'messagingAutomationNew'],
    '/messaging/providers': ['MessagingProviders', 'messagingProviders'],
    '/messaging/providers/:id': ['MessagingProviders', 'messagingProvider'],
    '/messaging/providers/new': ['MessagingProviders', 'messagingProviderNew'],
    '/messaging/providers/new/*': ['MessagingProviders', 'messagingProviderNew'],
    '/messaging/broadcasts': ['MessagingBroadcasts', 'messagingBroadcasts'],
    '/messaging/broadcasts/:id': ['MessagingBroadcasts', 'messagingBroadcast'],
    '/messaging/broadcasts/new': ['MessagingBroadcasts', 'messagingBroadcastNew'],
    '/messaging/library': ['MessagingLibrary', 'messagingLibrary'],
    '/messaging/library/new': ['MessagingLibrary', 'messagingLibraryNew'],
    '/messaging/library/:id': ['MessagingLibrary', 'messagingLibraryTemplate'],
}

/** This const is auto-generated, as is the whole file */
export const productRedirects: Record<
    string,
    string | ((params: Params, searchParams: Params, hashParams: Params) => string)
> = { '/messaging': '/messaging/broadcasts' }

/** This const is auto-generated, as is the whole file */
export const productConfiguration: Record<string, any> = {
    EarlyAccessFeatures: {
        name: 'Early Access Features',
        projectBased: true,
        defaultDocsPath: '/docs/feature-flags/early-access-feature-management',
        activityScope: 'EarlyAccessFeature',
    },
    EarlyAccessFeature: {
        name: 'Early Access Features',
        projectBased: true,
        defaultDocsPath: '/docs/feature-flags/early-access-feature-management',
        activityScope: 'EarlyAccessFeature',
    },
    LLMObservability: {
        projectBased: true,
        name: 'LLM observability',
        activityScope: 'LLMObservability',
        layout: 'app-container',
        defaultDocsPath: '/docs/ai-engineering/observability',
    },
    LLMObservabilityTrace: {
        projectBased: true,
        name: 'LLM observability trace',
        activityScope: 'LLMObservability',
        layout: 'app-container',
        defaultDocsPath: '/docs/ai-engineering/observability',
    },
    LLMObservabilityUsers: {
        projectBased: true,
        name: 'LLM observability users',
        activityScope: 'LLMObservability',
        layout: 'app-container',
        defaultDocsPath: '/docs/ai-engineering/observability',
    },
    MessagingAutomations: { name: 'Messaging', projectBased: true },
    MessagingBroadcasts: { name: 'Messaging', projectBased: true },
    MessagingProviders: { name: 'Messaging', projectBased: true },
    MessagingLibrary: { name: 'Messaging', projectBased: true },
}

/** This const is auto-generated, as is the whole file */
export const productUrls = {
    dashboards: (): string => '/dashboard',
    dashboard: (id: string | number, highlightInsightId?: string): string =>
        combineUrl(`/dashboard/${id}`, highlightInsightId ? { highlightInsightId } : {}).url,
    dashboardTextTile: (id: string | number, textTileId: string | number): string =>
        `${urls.dashboard(id)}/text-tiles/${textTileId}`,
    dashboardSharing: (id: string | number): string => `/dashboard/${id}/sharing`,
    dashboardSubscriptions: (id: string | number): string => `/dashboard/${id}/subscriptions`,
    dashboardSubscription: (id: string | number, subscriptionId: string): string =>
        `/dashboard/${id}/subscriptions/${subscriptionId}`,
    sharedDashboard: (shareToken: string): string => `/shared_dashboard/${shareToken}`,
    earlyAccessFeatures: (): string => '/early_access_features',
    earlyAccessFeature: (id: string): string => `/early_access_features/${id}`,
    experiment: (
        id: string | number,
        options?: {
            metric?: ExperimentTrendsQuery | ExperimentFunnelsQuery
            name?: string
        }
    ): string => `/experiments/${id}${options ? `?${toParams(options)}` : ''}`,
    experiments: (): string => '/experiments',
    experimentsSharedMetrics: (): string => '/experiments/shared-metrics',
    experimentsSharedMetric: (id: string | number): string => `/experiments/shared-metrics/${id}`,
    featureFlags: (tab?: string): string => `/feature_flags${tab ? `?tab=${tab}` : ''}`,
    featureFlag: (id: string | number): string => `/feature_flags/${id}`,
    featureFlagDuplicate: (sourceId: number | string | null): string => `/feature_flags/new?sourceId=${sourceId}`,
    groups: (groupTypeIndex: string | number): string => `/groups/${groupTypeIndex}`,
    group: (groupTypeIndex: string | number, groupKey: string, encode: boolean = true, tab?: string | null): string =>
        `/groups/${groupTypeIndex}/${encode ? encodeURIComponent(groupKey) : groupKey}${tab ? `/${tab}` : ''}`,
    llmObservabilityDashboard: (): string => '/llm-observability',
    llmObservabilityGenerations: (): string => '/llm-observability/generations',
    llmObservabilityTraces: (): string => '/llm-observability/traces',
    llmObservabilityTrace: (
        id: string,
        params?: {
            event?: string
            timestamp?: string
        }
    ): string => {
        const queryParams = new URLSearchParams(params)
        const stringifiedParams = queryParams.toString()
        return `/llm-observability/traces/${id}${stringifiedParams ? `?${stringifiedParams}` : ''}`
    },
    llmObservabilityUsers: (): string => '/llm-observability/users',
    messagingAutomations: (): string => '/messaging/automations',
    messagingAutomation: (id?: string): string => `/messaging/automations/${id}`,
    messagingAutomationNew: (): string => '/messaging/automations/new',
    messagingBroadcasts: (): string => '/messaging/broadcasts',
    messagingBroadcast: (id?: string): string => `/messaging/broadcasts/${id}`,
    messagingBroadcastNew: (): string => '/messaging/broadcasts/new',
    messagingProviders: (): string => '/messaging/providers',
    messagingProvider: (id?: string): string => `/messaging/providers/${id}`,
    messagingProviderNew: (template?: string): string => '/messaging/providers/new' + (template ? `/${template}` : ''),
    messagingLibrary: (): string => '/messaging/library',
    messagingLibraryNew: (): string => '/messaging/library/new',
    messagingLibraryTemplate: (id?: string): string => `/messaging/library/${id}`,
    notebooks: (): string => '/notebooks',
    notebook: (shortId: string): string => `/notebooks/${shortId}`,
    canvas: (): string => `/canvas`,
    personByDistinctId: (id: string, encode: boolean = true): string =>
        encode ? `/person/${encodeURIComponent(id)}` : `/person/${id}`,
    personByUUID: (uuid: string, encode: boolean = true): string =>
        encode ? `/persons/${encodeURIComponent(uuid)}` : `/persons/${uuid}`,
    persons: (): string => '/persons',
    insights: (): string => '/insights',
    insightNew: ({
        type,
        dashboardId,
        query,
    }: {
        type?: InsightType
        dashboardId?: DashboardType['id'] | null
        query?: Node
    } = {}): string =>
        combineUrl('/insights/new', dashboardId ? { dashboard: dashboardId } : {}, {
            ...(type ? { insight: type } : {}),
            ...(query ? { q: typeof query === 'string' ? query : JSON.stringify(query) } : {}),
        }).url,
    insightNewHogQL: ({ query, filters }: { query: string; filters?: HogQLFilters }): string =>
        combineUrl(
            `/data-warehouse`,
            {},
            { q: JSON.stringify({ kind: 'DataTableNode', full: true, source: { kind: 'HogQLQuery', query, filters } }) }
        ).url,
    insightEdit: (id: InsightShortId): string => `/insights/${id}/edit`,
    insightView: (
        id: InsightShortId,
        dashboardId?: number,
        variablesOverride?: Record<string, HogQLVariable>
    ): string => {
        const params = [
            { param: 'dashboard', value: dashboardId },
            { param: 'variables_override', value: variablesOverride },
        ]
            .filter((n) => Boolean(n.value))
            .map((n) => `${n.param}=${encodeURIComponent(JSON.stringify(n.value))}`)
            .join('&')
        return `/insights/${id}${params.length ? `?${params}` : ''}`
    },
    insightSubcriptions: (id: InsightShortId): string => `/insights/${id}/subscriptions`,
    insightSubcription: (id: InsightShortId, subscriptionId: string): string =>
        `/insights/${id}/subscriptions/${subscriptionId}`,
    insightSharing: (id: InsightShortId): string => `/insights/${id}/sharing`,
    savedInsights: (tab?: string): string => `/insights${tab ? `?tab=${tab}` : ''}`,
    insightAlerts: (insightShortId: InsightShortId): string => `/insights/${insightShortId}/alerts`,
    insightAlert: (insightShortId: InsightShortId, alertId: AlertType['id']): string =>
        `/insights/${insightShortId}/alerts?alert_id=${alertId}`,
    alert: (alertId: string): string => `/insights?tab=alerts&alert_id=${alertId}`,
    alerts: (): string => `/insights?tab=alerts`,
    replay: (
        tab?: ReplayTabs,
        filters?: Partial<RecordingUniversalFilters>,
        sessionRecordingId?: string,
        order?: string
    ): string =>
        combineUrl(tab ? `/replay/${tab}` : '/replay/home', {
            ...(filters ? { filters } : {}),
            ...(sessionRecordingId ? { sessionRecordingId } : {}),
            ...(order ? { order } : {}),
        }).url,
    replayPlaylist: (id: string): string => `/replay/playlists/${id}`,
    replaySingle: (id: string): string => `/replay/${id}`,
    replayFilePlayback: (): string => '/replay/file-playback',
    replaySettings: (sectionId?: string): string => `/replay/settings${sectionId ? `?sectionId=${sectionId}` : ''}`,
    webAnalytics: (): string => `/web`,
    webAnalyticsWebVitals: (): string => `/web/web-vitals`,
    webAnalyticsPageReports: (): string => `/web/page-reports`,
}

/** This const is auto-generated, as is the whole file */
export const fileSystemTypes = {
    broadcast: { icon: <IconMegaphone />, href: (ref: string) => urls.messagingBroadcast(ref) },
    dashboard: { icon: <IconDashboard />, href: (ref: string) => urls.dashboard(ref) },
    experiment: { icon: <IconTestTube />, href: (ref: string) => urls.experiment(ref) },
    feature_flag: { icon: <IconToggle />, href: (ref: string) => urls.featureFlag(ref) },
    insight: { icon: <IconGraph />, href: (ref: string) => urls.insightView(ref as InsightShortId) },
    notebook: { icon: <IconNotebook />, href: (ref: string) => urls.notebook(ref) },
}

/** This const is auto-generated, as is the whole file */
export const treeItems = [
    { path: `Create new/Broadcast`, type: 'broadcast', href: () => urls.messagingBroadcastNew() },
    { path: `Create new/Dashboard`, type: 'dashboard', href: () => urls.dashboards() + '#newDashboard=modal' },
    { path: `Create new/Experiment`, type: 'experiment', href: () => urls.experiment('new') },
    { path: `Create new/Feature flag`, type: 'feature_flag', href: () => urls.featureFlag('new') },
    { path: `Create new/Insight/Funnels`, type: 'insight', href: () => urls.insightNew({ type: InsightType.FUNNELS }) },
    {
        path: `Create new/Insight/Lifecycle`,
        type: 'insight',
        href: () => urls.insightNew({ type: InsightType.LIFECYCLE }),
    },
    {
        path: `Create new/Insight/Retention`,
        type: 'insight',
        href: () => urls.insightNew({ type: InsightType.RETENTION }),
    },
    {
        path: `Create new/Insight/Stickiness`,
        type: 'insight',
        href: () => urls.insightNew({ type: InsightType.STICKINESS }),
    },
    { path: `Create new/Insight/Trends`, type: 'insight', href: () => urls.insightNew({ type: InsightType.TRENDS }) },
    {
        path: `Create new/Insight/User paths`,
        type: 'insight',
        href: () => urls.insightNew({ type: InsightType.PATHS }),
    },
    { path: `Create new/Notebook`, type: 'notebook', href: () => urls.notebook('new') },
    { path: 'Explore/Early access features', icon: <IconRocket />, href: () => urls.earlyAccessFeatures() },
    { path: 'Explore/People and groups/People', icon: <IconPerson />, href: () => urls.persons() },
    { path: 'Explore/Recordings/Playlists', href: () => urls.replay(ReplayTabs.Playlists), icon: <IconRewindPlay /> },
    { path: 'Explore/Recordings/Recordings', href: () => urls.replay(ReplayTabs.Home), icon: <IconRewindPlay /> },
    { path: 'Explore/Recordings/Settings', href: () => urls.replay(ReplayTabs.Settings), icon: <IconRewindPlay /> },
    {
        path: 'Explore/Recordings/What to watch',
        href: () => urls.replay(ReplayTabs.Templates),
        icon: <IconRewindPlay />,
    },
    { path: 'Explore/Web Analytics', icon: <IconPieChart />, href: () => urls.webAnalytics() },
]
