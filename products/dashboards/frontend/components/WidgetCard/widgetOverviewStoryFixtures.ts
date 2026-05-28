import type { DashboardWidgetCatalogKey } from '../../widget_types/catalog'
import { DASHBOARD_WIDGET_CATALOG } from '../../widget_types/catalog'

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

/** New widget types: add a case here. See products/dashboards/CONTRIBUTING.md. */
export function getWidgetOverviewDemoState(catalogKey: DashboardWidgetCatalogKey): WidgetOverviewDemoState {
    const catalogEntry = DASHBOARD_WIDGET_CATALOG[catalogKey]
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
        default: {
            const exhaustiveCheck: never = catalogKey
            return exhaustiveCheck
        }
    }
}
