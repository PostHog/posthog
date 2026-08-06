import type { DashboardWidgetCatalogKey } from '../../widget_types/catalog'
import { getDashboardWidgetCatalogEntry } from '../../widget_types/catalog'
import { activityEventsSampleEvents } from '../../widgets/activity/activityEventsSampleData'
import { logsWidgetSampleLogLines } from '../../widgets/logs/logsWidgetSampleData'

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

export const experimentsSampleListRows = [
    {
        id: 101,
        name: 'New signup CTA',
        status: 'running',
        conclusion: null,
        start_date: '2026-05-12T00:00:00.000Z',
        end_date: null,
        created_at: '2026-05-10T09:00:00.000Z',
        feature_flag_key: 'new-signup-cta',
        created_by: { id: 1, first_name: 'Alex', email: 'alex@example.test' },
    },
    {
        id: 102,
        name: 'Pricing page layout',
        status: 'draft',
        conclusion: null,
        start_date: null,
        end_date: null,
        created_at: '2026-05-18T14:30:00.000Z',
        feature_flag_key: 'pricing-page-layout',
        created_by: { id: 2, first_name: 'Sam', email: 'sam@example.test' },
    },
    {
        id: 103,
        name: 'Onboarding checklist copy',
        status: 'stopped',
        conclusion: 'won',
        start_date: '2026-04-01T00:00:00.000Z',
        end_date: '2026-04-22T00:00:00.000Z',
        created_at: '2026-03-28T11:00:00.000Z',
        feature_flag_key: 'onboarding-checklist-copy',
        created_by: { id: 1, first_name: 'Alex', email: 'alex@example.test' },
    },
]

export const experimentResultsSamplePayload = {
    experiment: {
        id: 101,
        name: 'New signup CTA',
        status: 'running',
        start_date: '2026-05-12T00:00:00.000Z',
        end_date: null,
        feature_flag_key: 'new-signup-cta',
    },
    metrics: [
        {
            uuid: 'metric-1',
            name: 'Signup conversion',
            metric: {
                kind: 'ExperimentMetric',
                metric_type: 'funnel',
                uuid: 'metric-1',
                name: 'Signup conversion',
                series: [{ kind: 'EventsNode', event: 'signed_up' }],
            },
            result: {
                baseline: {
                    key: 'control',
                    number_of_samples: 4321,
                    sum: 980,
                    sum_squares: 980,
                },
                variant_results: [
                    {
                        key: 'test',
                        method: 'bayesian',
                        number_of_samples: 4287,
                        sum: 1112,
                        sum_squares: 1112,
                        chance_to_win: 0.92,
                        credible_interval: [0.012, 0.131],
                        significant: false,
                    },
                ],
            },
            error: null,
        },
    ],
    secondaryMetrics: [
        {
            uuid: 'secondary-1',
            name: 'Revenue per user',
            metric: {
                kind: 'ExperimentMetric',
                metric_type: 'mean',
                uuid: 'secondary-1',
                name: 'Revenue per user',
                source: { kind: 'EventsNode', event: 'purchase' },
            },
            result: {
                baseline: {
                    key: 'control',
                    number_of_samples: 4321,
                    sum: 8600,
                    sum_squares: 21400,
                },
                variant_results: [
                    {
                        key: 'test',
                        method: 'bayesian',
                        number_of_samples: 4287,
                        sum: 9120,
                        sum_squares: 23900,
                        chance_to_win: 0.78,
                        credible_interval: [-0.004, 0.061],
                        significant: false,
                    },
                ],
            },
            error: null,
        },
    ],
    totalMetricsCount: 1,
    totalSecondaryMetricsCount: 1,
}

export const surveyResultsSamplePayload = {
    survey: {
        id: 'survey-101',
        name: 'Post-purchase feedback',
        type: 'popover',
        archived: false,
        start_date: '2026-05-12T00:00:00.000Z',
        end_date: null,
    },
    stats: {
        'survey shown': {
            total_count: 1840,
            total_count_only_seen: 1180,
            unique_persons: 1640,
            unique_persons_only_seen: 1040,
            first_seen: '2026-05-12T00:00:00.000Z',
            last_seen: '2026-06-20T00:00:00.000Z',
        },
        'survey dismissed': {
            total_count: 240,
            total_count_only_seen: 0,
            unique_persons: 220,
            unique_persons_only_seen: 0,
            first_seen: '2026-05-12T00:00:00.000Z',
            last_seen: '2026-06-20T00:00:00.000Z',
        },
        'survey sent': {
            total_count: 420,
            total_count_only_seen: 0,
            unique_persons: 400,
            unique_persons_only_seen: 0,
            first_seen: '2026-05-12T00:00:00.000Z',
            last_seen: '2026-06-20T00:00:00.000Z',
        },
    },
    rates: {
        response_rate: 22.83,
        dismissal_rate: 13.04,
        unique_users_response_rate: 24.39,
        unique_users_dismissal_rate: 13.41,
    },
    responses: [
        {
            uuid: 'response-1',
            distinct_id: 'user_8421',
            session_id: 'session-1',
            submitted_at: '2026-06-20T14:31:00.000Z',
            answers: [
                { question_id: 'q1', question_text: 'How satisfied are you?', question_type: 'rating', answer: '9' },
                {
                    question_id: 'q2',
                    question_text: 'What can we improve?',
                    question_type: 'open',
                    answer: 'Faster checkout would be great.',
                },
            ],
        },
        {
            uuid: 'response-2',
            distinct_id: 'user_5530',
            session_id: 'session-2',
            submitted_at: '2026-06-20T11:02:00.000Z',
            answers: [
                { question_id: 'q1', question_text: 'How satisfied are you?', question_type: 'rating', answer: '6' },
            ],
        },
    ],
    hasMore: true,
}

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
        case 'activity_events_list':
            return {
                title: defaultTitle,
                description: catalogEntry.description,
                showDescription: true,
                config: { ...defaultConfig },
                loading: false,
                result: {
                    results: activityEventsSampleEvents,
                    hasMore: true,
                    limit: 10,
                    totalCount: 25,
                    totalCountCapped: true,
                },
            }
        case 'experiments_list':
            return {
                title: defaultTitle,
                description: catalogEntry.description,
                showDescription: true,
                config: defaultConfig,
                loading: false,
                result: {
                    results: experimentsSampleListRows,
                    hasMore: true,
                    limit: 10,
                    totalCount: 12,
                    totalCountCapped: false,
                },
            }
        case 'experiment_results':
            return {
                title: defaultTitle,
                description: catalogEntry.description,
                showDescription: true,
                config: { ...defaultConfig, experimentId: 101 },
                loading: false,
                result: experimentResultsSamplePayload,
            }
        case 'survey_results':
            return {
                title: defaultTitle,
                description: catalogEntry.description,
                showDescription: true,
                config: { ...defaultConfig, surveyId: 'survey-101' },
                loading: false,
                result: surveyResultsSamplePayload,
            }
        case 'logs_list':
            return {
                title: defaultTitle,
                description: catalogEntry.description,
                showDescription: true,
                config: { ...defaultConfig },
                loading: false,
                result: {
                    results: logsWidgetSampleLogLines,
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
