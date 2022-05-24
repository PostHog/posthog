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
                    after: {
                        groups: [
                            {
                                properties: [{ key: 'id', type: 'cohort', value: 98, operator: null }],
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

export const personActivityResponseJson: ActivityLogItem[] = []

export const insightsActivityResponseJson: ActivityLogItem[] = [
    {
        user: { first_name: 'Cameron', email: 'cameron@posthog.com' },
        activity: 'created',
        scope: ActivityScope.INSIGHT,
        item_id: '738510',
        detail: { changes: null, merge: null, name: null, short_id: '0GUplMDf' as InsightShortId },
        created_at: '2022-05-03T16:28:38.470679Z',
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
        detail: { changes: null, merge: null, name: 'Pageview count', short_id: 'iVXqSrre' as InsightShortId },
        created_at: '2022-05-03T15:27:14.031192Z',
    },
    {
        user: { first_name: 'Cameron', email: 'cameron@posthog.com' },
        activity: 'created',
        scope: ActivityScope.INSIGHT,
        item_id: '738027',
        detail: { changes: null, merge: null, name: null, short_id: '4vIGUyy1' as InsightShortId },
        created_at: '2022-05-03T15:24:03.779164Z',
    },
]
