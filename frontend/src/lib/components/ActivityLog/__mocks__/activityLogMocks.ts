import { ActivityLogItem, ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'
import { InsightShortId } from '~/types'

export const featureFlagsActivityResponseJson: ActivityLogItem[] = [
    {
        user: {
            first_name: 'Neil',
            email: 'neil@posthog.com',
        },
        activity: 'updated',
        scope: ActivityScope.FEATURE_FLAG,
        item_id: '2348',
        detail: {
            changes: [
                {
                    type: 'FeatureFlag',
                    action: 'changed',
                    field: 'filters',
                    before: {
                        groups: [
                            {
                                properties: [
                                    {
                                        key: 'id',
                                        type: 'cohort',
                                        value: 98,
                                        operator: null,
                                    },
                                ],
                                rollout_percentage: null,
                            },
                            {
                                properties: [],
                                rollout_percentage: 30,
                            },
                        ],
                        multivariate: null,
                    },
                    after: {
                        groups: [
                            {
                                properties: [
                                    {
                                        key: 'id',
                                        type: 'cohort',
                                        value: 98,
                                        operator: null,
                                    },
                                ],
                                rollout_percentage: null,
                            },
                        ],
                        multivariate: null,
                    },
                },
            ],
            merge: null,
            name: 'cohort-filters',
            short_id: null,
        },
        created_at: '2022-05-24T12:28:14.507709Z',
    },
    {
        user: { first_name: 'Alex Kim', email: 'alex@posthog.com' },
        activity: 'updated',
        scope: ActivityScope.FEATURE_FLAG,
        item_id: '1474',
        detail: {
            merge: null,
            changes: [
                {
                    type: 'FeatureFlag',
                    action: 'changed',
                    field: 'filters',
                    before: {
                        groups: [
                            {
                                properties: [
                                    {
                                        key: 'id',
                                        type: 'cohort',
                                        value: 98,
                                        operator: null,
                                    },
                                ],
                                rollout_percentage: null,
                            },
                            {
                                properties: [],
                                rollout_percentage: 30,
                            },
                        ],
                        multivariate: null,
                    },
                    after: {
                        groups: [
                            {
                                properties: [
                                    {
                                        key: 'id',
                                        type: 'cohort',
                                        value: 98,
                                        operator: null,
                                    },
                                ],
                                rollout_percentage: null,
                            },
                        ],
                        multivariate: null,
                    },
                },
            ],
            name: 'data-management',
        },
        created_at: '2022-03-21T15:58:55.792014Z',
    },
    {
        user: { first_name: 'Neil', email: 'neil@posthog.com' },
        activity: 'updated',
        scope: ActivityScope.FEATURE_FLAG,
        item_id: '1846',
        detail: {
            merge: null,
            changes: [{ type: 'FeatureFlag', action: 'changed', field: 'deleted', before: false, after: true }],
            name: 'test-ff',
        },
        created_at: '2022-03-21T15:50:25.894422Z',
    },
    {
        user: { first_name: 'Neil', email: 'neil@posthog.com' },
        activity: 'created',
        scope: ActivityScope.FEATURE_FLAG,
        item_id: '1846',
        detail: {
            merge: null,
            changes: null,
            name: 'test-ff',
        },
        created_at: '2022-03-21T15:50:15.625221Z',
    },
    {
        user: { first_name: 'Paul', email: 'paul@posthog.com' },
        activity: 'created',
        scope: ActivityScope.FEATURE_FLAG,
        item_id: '1825',
        detail: {
            merge: null,
            changes: null,
            name: 'feature_that_will_dazzle',
        },
        created_at: '2022-03-21T13:22:14.605131Z',
    },
    {
        user: { first_name: 'Paul', email: 'paul@posthog.com' },
        activity: 'updated',
        scope: ActivityScope.FEATURE_FLAG,
        item_id: '1353',
        detail: {
            merge: null,
            changes: [
                {
                    type: 'FeatureFlag',
                    action: 'changed',
                    field: 'filters',
                    before: {
                        groups: [
                            {
                                properties: [
                                    { key: 'id', type: 'cohort', value: 98, operator: null },
                                    { key: 'id', type: 'cohort', value: 641, operator: null },
                                ],
                                rollout_percentage: null,
                            },
                            {
                                properties: [
                                    {
                                        key: 'email',
                                        type: 'person',
                                        value: ['paul.dambra@gmail.com'],
                                        operator: 'exact',
                                    },
                                ],
                                rollout_percentage: null,
                            },
                            {
                                properties: [
                                    {
                                        key: 'email',
                                        type: 'person',
                                        value: ['christopher@imusician.pro'],
                                        operator: 'exact',
                                    },
                                ],
                                rollout_percentage: null,
                            },
                            {
                                properties: [{ key: 'id', type: 'cohort', value: 411, operator: null }],
                                rollout_percentage: 50,
                            },
                        ],
                        multivariate: null,
                    },
                    after: {
                        groups: [
                            {
                                properties: [
                                    { key: 'id', type: 'cohort', value: 98, operator: null },
                                    { key: 'id', type: 'cohort', value: 641, operator: null },
                                ],
                                rollout_percentage: null,
                            },
                            {
                                properties: [
                                    {
                                        key: 'email',
                                        type: 'person',
                                        value: ['paul.dambra@gmail.com'],
                                        operator: 'exact',
                                    },
                                ],
                                rollout_percentage: null,
                            },
                            {
                                properties: [
                                    {
                                        key: 'email',
                                        type: 'person',
                                        value: ['christopher@imusician.pro'],
                                        operator: 'exact',
                                    },
                                ],
                                rollout_percentage: null,
                            },
                            {
                                properties: [{ key: 'id', type: 'cohort', value: 411, operator: null }],
                                rollout_percentage: 100,
                            },
                        ],
                        multivariate: null,
                    },
                },
            ],
            name: 'fantastic_new_feature',
        },
        created_at: '2022-03-21T12:48:27.811085Z',
    },
    {
        user: { first_name: 'James', email: 'fuziontech@gmail.com' },
        activity: 'updated',
        scope: ActivityScope.FEATURE_FLAG,
        item_id: '984',
        detail: {
            merge: null,
            changes: [{ type: 'FeatureFlag', action: 'changed', field: 'active', before: true, after: false }],
            name: 'cloud-announcement',
        },
        created_at: '2022-03-20T15:26:58.006900Z',
    },
    {
        user: { first_name: 'James', email: 'fuziontech@gmail.com' },
        activity: 'updated',
        scope: ActivityScope.FEATURE_FLAG,
        item_id: '984',
        detail: {
            merge: null,
            changes: [{ type: 'FeatureFlag', action: 'changed', field: 'active', before: false, after: true }],
            name: 'cloud-announcement',
        },
        created_at: '2022-03-20T15:26:46.397726Z',
    },
    {
        user: { first_name: 'James', email: 'fuziontech@gmail.com' },
        activity: 'updated',
        scope: ActivityScope.FEATURE_FLAG,
        item_id: '984',
        detail: {
            merge: null,
            changes: [
                {
                    type: 'FeatureFlag',
                    action: 'changed',
                    field: 'filters',
                    before: {
                        groups: [
                            {
                                properties: [{ key: 'realm', type: 'person', value: ['cloud'], operator: 'exact' }],
                                rollout_percentage: null,
                            },
                        ],
                        multivariate: {
                            variants: [
                                {
                                    key: 'Dec 7: Event ingestion is delayed due to ongoing AWS issues. No events are being dropped, but we are unable to process them at the moment',
                                    name: 'AWS issues impacting plugin server',
                                    rollout_percentage: 100,
                                },
                            ],
                        },
                    },
                    after: {
                        groups: [
                            {
                                properties: [{ key: 'realm', type: 'person', value: ['cloud'], operator: 'exact' }],
                                rollout_percentage: null,
                            },
                        ],
                        multivariate: {
                            variants: [
                                {
                                    key: 'Mar_20_Some_counts_and_aggregates_may_be_slightly_low_due_to_maintenance_with_ClickHouse_This_will_be_resolved_by_Monday',
                                    name: 'ClickHouse Maintenance',
                                    rollout_percentage: 100,
                                },
                            ],
                        },
                    },
                },
            ],
            name: 'cloud-announcement',
        },
        created_at: '2022-03-20T15:26:13.314035Z',
    },
    {
        user: { first_name: 'Alex Kim', email: 'alex@posthog.com' },
        activity: 'updated',
        scope: ActivityScope.FEATURE_FLAG,
        item_id: '1474',
        detail: {
            merge: null,
            changes: [
                {
                    type: 'FeatureFlag',
                    action: 'changed',
                    field: 'filters',
                    before: {
                        groups: [
                            {
                                properties: [{ key: 'id', type: 'cohort', value: 98, operator: null }],
                                rollout_percentage: null,
                            },
                        ],
                        multivariate: null,
                    },
                    after: {
                        groups: [
                            {
                                properties: [{ key: 'id', type: 'cohort', value: 98, operator: null }],
                                rollout_percentage: null,
                            },
                            {
                                properties: [{ key: 'id', type: 'cohort', value: 411, operator: null }],
                                rollout_percentage: 50,
                            },
                        ],
                        multivariate: null,
                    },
                },
            ],
            name: 'data-management',
        },
        created_at: '2022-03-19T16:58:47.747634Z',
    },
]

export const personActivityResponseJson: ActivityLogItem[] = [
    {
        user: { first_name: 'Paul', email: 'paul.dambra@gmail.com' },
        activity: 'updated',
        scope: ActivityScope.PERSON,
        item_id: '502792727',
        detail: {
            changes: [{ type: 'Person', action: 'changed', field: 'properties', before: undefined, after: undefined }],
            merge: null,
            name: null,
            short_id: null,
        },
        created_at: '2022-06-23T20:53:09.806219Z',
    },
    {
        user: { first_name: 'Paul', email: 'paul.dambra@gmail.com' },
        activity: 'people_merged_into',
        scope: ActivityScope.PERSON,
        item_id: '502792727',
        detail: {
            changes: null,
            merge: {
                type: 'Person',
                source: [
                    {
                        id: 502746582,
                        name: '1819231753016b-0b04ab5a3ab143-3297640-75300-181923175313d4',
                        uuid: '01819231-75a0-0000-467e-a4be57b44a37',
                        created_at: '2022-06-23T20:12:03.828000Z',
                        properties: {
                            $geoip_latitude: 51.5368,
                            $geoip_city_name: 'London',
                            $geoip_longitude: -0.6718,
                            $geoip_time_zone: 'Europe/London',
                            $initial_pathname: '/',
                            $initial_referrer: '$direct',
                            $geoip_postal_code: 'SL1',
                            $geoip_country_code: 'GB',
                            $geoip_country_name: 'United Kingdom',
                            $initial_current_url: 'https://pauldambra.dev/',
                            $initial_device_type: 'Desktop',
                            $geoip_continent_code: 'EU',
                            $geoip_continent_name: 'Europe',
                            $initial_geoip_latitude: 51.5368,
                            $initial_browser_version: null,
                            $initial_geoip_city_name: 'London',
                            $initial_geoip_longitude: -0.6718,
                            $initial_geoip_time_zone: 'Europe/London',
                            $geoip_subdivision_1_code: 'ENG',
                            $geoip_subdivision_1_name: 'England',
                            $initial_referring_domain: '$direct',
                            $initial_geoip_postal_code: 'SL1',
                            $initial_geoip_country_code: 'GB',
                            $initial_geoip_country_name: 'United Kingdom',
                            $initial_geoip_continent_code: 'EU',
                            $initial_geoip_continent_name: 'Europe',
                            $initial_geoip_subdivision_1_code: 'ENG',
                            $initial_geoip_subdivision_1_name: 'England',
                        },
                        distinct_ids: ['1819231753016b-0b04ab5a3ab143-3297640-75300-181923175313d4'],
                    },
                    {
                        id: 502725471,
                        name: '1819220a99e5ec-0005fee037f8d2-3297640-75300-1819220a99f6b7',
                        uuid: '01819220-aa0b-0000-6992-fad9de0ea4dc',
                        created_at: '2022-06-23T19:53:43.137000Z',
                        properties: {
                            $geoip_latitude: 51.5368,
                            $geoip_city_name: 'London',
                            $geoip_longitude: -0.6718,
                            $geoip_time_zone: 'Europe/London',
                            $initial_pathname: '/',
                            $initial_referrer: '$direct',
                            $geoip_postal_code: 'SL1',
                            $geoip_country_code: 'GB',
                            $geoip_country_name: 'United Kingdom',
                            $initial_current_url: 'https://pauldambra.dev/',
                            $initial_device_type: 'Desktop',
                            $geoip_continent_code: 'EU',
                            $geoip_continent_name: 'Europe',
                            $initial_geoip_latitude: 51.5368,
                            $initial_browser_version: null,
                            $initial_geoip_city_name: 'London',
                            $initial_geoip_longitude: -0.6718,
                            $initial_geoip_time_zone: 'Europe/London',
                            $geoip_subdivision_1_code: 'ENG',
                            $geoip_subdivision_1_name: 'England',
                            $initial_referring_domain: '$direct',
                            $initial_geoip_postal_code: 'SL1',
                            $initial_geoip_country_code: 'GB',
                            $initial_geoip_country_name: 'United Kingdom',
                            $initial_geoip_continent_code: 'EU',
                            $initial_geoip_continent_name: 'Europe',
                            $initial_geoip_subdivision_1_code: 'ENG',
                            $initial_geoip_subdivision_1_name: 'England',
                        },
                        distinct_ids: ['1819220a99e5ec-0005fee037f8d2-3297640-75300-1819220a99f6b7'],
                    },
                    {
                        id: 502715718,
                        name: '18192189287517-0e66a695611002-3297640-75300-18192189288790',
                        uuid: '01819218-92f2-0000-7132-90a079001dc9',
                        created_at: '2022-06-23T19:44:52.944000Z',
                        properties: {
                            $geoip_latitude: 51.5368,
                            $geoip_city_name: 'London',
                            $geoip_longitude: -0.6718,
                            $geoip_time_zone: 'Europe/London',
                            $initial_pathname: '/',
                            $initial_referrer: '$direct',
                            $geoip_postal_code: 'SL1',
                            $geoip_country_code: 'GB',
                            $geoip_country_name: 'United Kingdom',
                            $initial_current_url: 'https://pauldambra.dev/',
                            $initial_device_type: 'Desktop',
                            $geoip_continent_code: 'EU',
                            $geoip_continent_name: 'Europe',
                            $initial_geoip_latitude: 51.5368,
                            $initial_browser_version: null,
                            $initial_geoip_city_name: 'London',
                            $initial_geoip_longitude: -0.6718,
                            $initial_geoip_time_zone: 'Europe/London',
                            $geoip_subdivision_1_code: 'ENG',
                            $geoip_subdivision_1_name: 'England',
                            $initial_referring_domain: '$direct',
                            $initial_geoip_postal_code: 'SL1',
                            $initial_geoip_country_code: 'GB',
                            $initial_geoip_country_name: 'United Kingdom',
                            $initial_geoip_continent_code: 'EU',
                            $initial_geoip_continent_name: 'Europe',
                            $initial_geoip_subdivision_1_code: 'ENG',
                            $initial_geoip_subdivision_1_name: 'England',
                        },
                        distinct_ids: ['18192189287517-0e66a695611002-3297640-75300-18192189288790'],
                    },
                    {
                        id: 502696118,
                        name: '1819208c6ed32c-0e427ef09bbae-3297640-75300-1819208c6ee74b',
                        uuid: '01819208-c74f-0000-75e7-7d3dc16da26b',
                        created_at: '2022-06-23T19:27:37.771000Z',
                        properties: {
                            $geoip_latitude: 51.5368,
                            $geoip_city_name: 'London',
                            $geoip_longitude: -0.6718,
                            $geoip_time_zone: 'Europe/London',
                            $initial_pathname: '/',
                            $initial_referrer: '$direct',
                            $geoip_postal_code: 'SL1',
                            $geoip_country_code: 'GB',
                            $geoip_country_name: 'United Kingdom',
                            $initial_current_url: 'https://pauldambra.dev/',
                            $initial_device_type: 'Desktop',
                            $geoip_continent_code: 'EU',
                            $geoip_continent_name: 'Europe',
                            $initial_geoip_latitude: 51.5368,
                            $initial_browser_version: null,
                            $initial_geoip_city_name: 'London',
                            $initial_geoip_longitude: -0.6718,
                            $initial_geoip_time_zone: 'Europe/London',
                            $geoip_subdivision_1_code: 'ENG',
                            $geoip_subdivision_1_name: 'England',
                            $initial_referring_domain: '$direct',
                            $initial_geoip_postal_code: 'SL1',
                            $initial_geoip_country_code: 'GB',
                            $initial_geoip_country_name: 'United Kingdom',
                            $initial_geoip_continent_code: 'EU',
                            $initial_geoip_continent_name: 'Europe',
                            $initial_geoip_subdivision_1_code: 'ENG',
                            $initial_geoip_subdivision_1_name: 'England',
                        },
                        distinct_ids: ['1819208c6ed32c-0e427ef09bbae-3297640-75300-1819208c6ee74b'],
                    },
                ],
                target: {
                    id: 502792727,
                    name: '1819220a99e5ec-0005fee037f8d2-3297640-75300-1819220a99f6b7',
                    uuid: '01819256-1d25-0000-4ed7-ea437589ada7',
                    created_at: '2022-06-23T20:52:06.053733Z',
                    properties: {},
                    distinct_ids: [
                        '1819220a99e5ec-0005fee037f8d2-3297640-75300-1819220a99f6b7',
                        '1819231753016b-0b04ab5a3ab143-3297640-75300-181923175313d4',
                        '1819249450126c-0162012e0be59d-3297640-75300-1819249450238e',
                    ],
                },
            },
            name: null,
            short_id: null,
        },
        created_at: '2022-06-23T20:52:53.637157Z',
    },
    {
        user: { first_name: 'Paul', email: 'paul.dambra@gmail.com' },
        activity: 'split_person',
        scope: ActivityScope.PERSON,
        item_id: '502792727',
        detail: {
            changes: [
                {
                    type: 'Person',
                    action: 'split',
                    field: undefined,
                    before: undefined,
                    after: {
                        distinct_ids: [
                            '1819208c6ed32c-0e427ef09bbae-3297640-75300-1819208c6ee74b',
                            '18192189287517-0e66a695611002-3297640-75300-18192189288790',
                            '1819220a99e5ec-0005fee037f8d2-3297640-75300-1819220a99f6b7',
                            '1819231753016b-0b04ab5a3ab143-3297640-75300-181923175313d4',
                            '1819249450126c-0162012e0be59d-3297640-75300-1819249450238e',
                        ],
                    },
                },
            ],
            merge: null,
            name: null,
            short_id: null,
        },
        created_at: '2022-06-23T20:53:17.620277Z',
    },
]

export const insightsActivityResponseJson: ActivityLogItem[] = [
    {
        user: {
            first_name: 'Ben',
            email: 'ben@posthog.com',
        },
        activity: 'exported',
        scope: ActivityScope.INSIGHT,
        item_id: '6',
        detail: {
            changes: [
                {
                    type: 'Insight',
                    action: 'exported',
                    field: 'export_format',
                    before: undefined,
                    after: 'image/png',
                },
            ],
            merge: null,
            name: 'Super B.I.',
            short_id: 'KQhbLk2R' as InsightShortId,
        },
        created_at: '2022-06-24T14:53:24.194502Z',
    },
    {
        user: { first_name: 'Cameron', email: 'cameron@posthog.com' },
        activity: 'created',
        scope: ActivityScope.INSIGHT,
        item_id: '738509',
        detail: { changes: null, merge: null, name: null, short_id: 'kUUjoSL9' as InsightShortId },
        created_at: '2022-05-03T16:28:29.544239Z',
    },
    {
        user: { first_name: 'Cameron', email: 'cameron@posthog.com' },
        activity: 'created',
        scope: ActivityScope.INSIGHT,
        item_id: '738495',
        detail: { changes: null, merge: null, name: null, short_id: 'sp1SXU36' as InsightShortId },
        created_at: '2022-05-03T16:27:26.942756Z',
    },
    {
        user: { first_name: 'Cameron', email: 'cameron@posthog.com' },
        activity: 'created',
        scope: ActivityScope.INSIGHT,
        item_id: '738494',
        detail: { changes: null, merge: null, name: null, short_id: '3wfG32yd' as InsightShortId },
        created_at: '2022-05-03T16:27:26.215581Z',
    },
    {
        user: { first_name: 'Cameron', email: 'cameron@posthog.com' },
        activity: 'created',
        scope: ActivityScope.INSIGHT,
        item_id: '738493',
        detail: { changes: null, merge: null, name: null, short_id: 'mFw8dLOL' as InsightShortId },
        created_at: '2022-05-03T16:27:23.649287Z',
    },
    {
        user: { first_name: 'Cameron', email: 'cameron@posthog.com' },
        activity: 'updated',
        scope: ActivityScope.INSIGHT,
        item_id: '738061',
        detail: {
            changes: [{ type: 'Insight', action: 'changed', field: 'name', before: 'cool insight', after: '' }],
            merge: null,
            name: 'Pageview count',
            short_id: 'iVXqSrre' as InsightShortId,
        },
        created_at: '2022-05-03T15:27:29.072978Z',
    },
    {
        user: { first_name: 'Paul', email: 'paul@posthog.com' },
        activity: 'updated',
        scope: ActivityScope.INSIGHT,
        item_id: '738061',
        detail: {
            name: 'DAU',
            merge: null,
            changes: [
                { type: 'Insight', action: 'changed', field: 'name', before: 'cool insight', after: 'DAU' },
                {
                    type: 'Insight',
                    after: {
                        events: [],
                        actions: [
                            {
                                id: '8917',
                                math: 'dau',
                                name: 'Popup or Notification',
                                type: 'actions',
                                order: 0,
                                properties: [],
                                custom_name: 'Extension',
                                math_property: null,
                            },
                            {
                                id: '14430',
                                math: 'dau',
                                name: 'appOpen OR onboardingOpen',
                                type: 'actions',
                                order: 1,
                                properties: [
                                    {
                                        key: 'nativeApplicationVersion',
                                        type: 'event',
                                        value: 'is_set',
                                        operator: 'is_set',
                                    },
                                ],
                                custom_name: 'Mobile',
                            },
                            {
                                id: '13927',
                                math: 'dau',
                                name: 'Client Open',
                                type: 'actions',
                                order: 2,
                                custom_name: 'Total',
                            },
                        ],
                        date_to: null,
                        display: 'ActionsLineGraph',
                        insight: 'TRENDS',
                        interval: 'day',
                        date_from: '-90d',
                        new_entity: [],
                        properties: [],
                        funnel_window_days: 14,
                    },
                    field: 'filters',
                    action: 'changed',
                    before: {
                        events: [],
                        actions: [
                            {
                                id: '8917',
                                math: 'dau',
                                name: 'Popup or Notification',
                                type: 'actions',
                                order: 0,
                                properties: [],
                                custom_name: 'Extension',
                                math_property: null,
                            },
                            {
                                id: '14430',
                                math: 'dau',
                                name: 'appOpen OR onboardingOpen',
                                type: 'actions',
                                order: 1,
                                properties: [],
                                custom_name: 'Mobile',
                            },
                            {
                                id: '13927',
                                math: 'dau',
                                name: 'Client Open',
                                type: 'actions',
                                order: 2,
                                custom_name: 'Total',
                            },
                        ],
                        date_to: null,
                        display: 'ActionsLineGraph',
                        insight: 'TRENDS',
                        interval: 'day',
                        date_from: '-90d',
                        new_entity: [],
                        properties: [],
                        funnel_window_days: 14,
                    },
                },
            ],
            short_id: 'eRY9-Frr' as InsightShortId,
        },
        created_at: '2022-05-03T15:27:29.072978Z',
    },
    {
        user: { first_name: 'Cameron', email: 'cameron@posthog.com' },
        activity: 'updated',
        scope: ActivityScope.INSIGHT,
        item_id: '738061',
        detail: {
            changes: [{ type: 'Insight', action: 'changed', field: 'name', before: '', after: 'cool insight' }],
            merge: null,
            name: 'cool insight',
            short_id: 'iVXqSrre' as InsightShortId,
        },
        created_at: '2022-05-03T15:27:20.265216Z',
    },
    {
        user: { first_name: 'Cameron', email: 'cameron@posthog.com' },
        activity: 'created',
        scope: ActivityScope.INSIGHT,
        item_id: '738061',
        detail: {
            changes: [{ type: 'Insight', action: 'changed', field: 'name', before: '', after: 'cool insight' }],
            merge: null,
            name: 'Pageview count',
            short_id: 'iVXqSrre' as InsightShortId,
        },
        created_at: '2022-05-03T15:27:14.031192Z',
    },
    {
        user: { first_name: 'Cameron', email: 'cameron@posthog.com' },
        activity: 'created',
        scope: ActivityScope.INSIGHT,
        item_id: '738027',
        detail: {
            changes: [{ type: 'Insight', action: 'changed', field: 'name', before: '', after: 'cool insight' }],
            merge: null,
            name: null,
            short_id: '4vIGUyy1' as InsightShortId,
        },
        created_at: '2022-05-03T15:24:03.779164Z',
    },
]
