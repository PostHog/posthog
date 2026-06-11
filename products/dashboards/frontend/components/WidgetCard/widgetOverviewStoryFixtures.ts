import type { DashboardWidgetCatalogKey } from '../../widget_types/catalog'
import { getDashboardWidgetCatalogEntry } from '../../widget_types/catalog'

export type WidgetOverviewDemoState = {
    title?: string
    description?: string
    showDescription?: boolean
    config: Record<string, unknown>
    loading: boolean
    result: unknown
    cardError?: string | null
}

export const errorTrackingSampleIssues = [
    {
        id: 'issue-1',
        name: 'TypeError: Cannot read properties of undefined',
        description: 'User profile settings fail to load when the session cache is empty.',
        function: 'loadProfile',
        source: 'https://app.example.test/static/js/settings.js',
        library: 'web',
        status: 'active',
        assignee: null,
        first_seen: '2026-05-01T10:00:00.000Z',
        last_seen: '2026-05-26T08:00:00.000Z',
        aggregations: {
            occurrences: 42,
            sessions: 18,
            users: 12,
            volume_buckets: [
                { label: '2026-05-20T00:00:00.000Z', value: 2 },
                { label: '2026-05-21T00:00:00.000Z', value: 4 },
                { label: '2026-05-22T00:00:00.000Z', value: 8 },
                { label: '2026-05-23T00:00:00.000Z', value: 12 },
                { label: '2026-05-24T00:00:00.000Z', value: 6 },
                { label: '2026-05-25T00:00:00.000Z', value: 5 },
                { label: '2026-05-26T00:00:00.000Z', value: 5 },
            ],
        },
    },
    {
        id: 'issue-2',
        name: 'NetworkError: Failed to fetch',
        description: 'Checkout requests fail when the payment API is unavailable.',
        function: 'fetch',
        source: 'https://app.example.test/static/js/api.js',
        library: 'web',
        status: 'pending_release',
        assignee: null,
        first_seen: '2026-05-10T10:00:00.000Z',
        last_seen: '2026-05-25T12:00:00.000Z',
        aggregations: {
            occurrences: 18,
            sessions: 9,
            users: 7,
            volume_buckets: [
                { label: '2026-05-20T00:00:00.000Z', value: 1 },
                { label: '2026-05-21T00:00:00.000Z', value: 2 },
                { label: '2026-05-22T00:00:00.000Z', value: 3 },
                { label: '2026-05-23T00:00:00.000Z', value: 2 },
                { label: '2026-05-24T00:00:00.000Z', value: 4 },
                { label: '2026-05-25T00:00:00.000Z', value: 3 },
                { label: '2026-05-26T00:00:00.000Z', value: 3 },
            ],
        },
    },
]

export const sessionReplaySampleRecordings = [
    {
        id: 'overview-recording-1',
        viewed: false,
        viewers: [],
        recording_duration: 248,
        start_time: '2026-05-26T08:00:00.000Z',
        end_time: '2026-05-26T08:04:08.000Z',
        distinct_id: 'user-1',
        click_count: 12,
        keypress_count: 34,
        person: {
            id: '1',
            name: 'Alex Chen',
            distinct_ids: ['user-1'],
            properties: {
                $geoip_country_code: 'US',
                $browser: 'Chrome',
                $device_type: 'Desktop',
                $os: 'Mac OS X',
            },
            created_at: '2026-05-01T10:00:00.000Z',
            is_identified: true,
        },
        activity_score: 76,
        snapshot_source: 'web' as const,
        start_url: 'https://app.example.test/dashboard',
    },
    {
        id: 'overview-recording-2',
        viewed: false,
        viewers: [],
        recording_duration: 132,
        start_time: '2026-05-25T12:00:00.000Z',
        end_time: '2026-05-25T12:02:12.000Z',
        distinct_id: 'user-2',
        click_count: 4,
        keypress_count: 9,
        person: {
            id: '2',
            name: 'Sam Rivera',
            distinct_ids: ['user-2'],
            properties: {
                $geoip_country_code: 'AU',
                $browser: 'Chrome',
                $device_type: 'Desktop',
                $os: 'Mac OS X',
            },
            created_at: '2026-05-01T10:00:00.000Z',
            is_identified: true,
        },
        activity_score: 48,
        snapshot_source: 'web' as const,
        start_url: 'https://app.example.test/settings',
    },
    {
        id: 'overview-recording-3',
        viewed: false,
        viewers: [],
        recording_duration: 89,
        start_time: '2026-05-24T15:00:00.000Z',
        end_time: '2026-05-24T15:01:29.000Z',
        distinct_id: 'user-3',
        click_count: 2,
        keypress_count: 5,
        person: {
            id: '3',
            name: 'Jordan Lee',
            distinct_ids: ['user-3'],
            properties: {
                $geoip_country_code: 'GB',
                $browser: 'Firefox',
                $device_type: 'Desktop',
                $os: 'Windows',
            },
            created_at: '2026-05-01T10:00:00.000Z',
            is_identified: true,
        },
        activity_score: 31,
        snapshot_source: 'web' as const,
        start_url: 'https://app.example.test/onboarding',
    },
]

/** New widget types: add a case here. See products/dashboards/CONTRIBUTING.md. */
export function getWidgetOverviewDemoState(catalogKey: DashboardWidgetCatalogKey): WidgetOverviewDemoState {
    const catalogEntry = getDashboardWidgetCatalogEntry(catalogKey)
    const defaultConfig = catalogEntry.defaultConfig as Record<string, unknown>
    const defaultTitle = catalogEntry.headerTitle ?? catalogEntry.label

    switch (catalogKey) {
        case 'error_tracking_list':
            return {
                title: defaultTitle,
                description: catalogEntry.description,
                showDescription: true,
                config: { ...defaultConfig, orderBy: 'occurrences' },
                loading: false,
                result: {
                    results: errorTrackingSampleIssues,
                    hasMore: true,
                    limit: 10,
                },
            }
        case 'session_replay_list':
            return {
                title: defaultTitle,
                description: catalogEntry.description,
                showDescription: true,
                config: { ...defaultConfig, orderBy: 'start_time' },
                loading: false,
                result: {
                    results: sessionReplaySampleRecordings,
                    hasMore: true,
                    limit: 10,
                    totalCount: 25,
                    totalCountCapped: true,
                },
            }
        default: {
            const exhaustiveCheck: never = catalogKey
            return exhaustiveCheck
        }
    }
}
