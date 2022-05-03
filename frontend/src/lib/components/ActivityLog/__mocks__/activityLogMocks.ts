import { ActivityLogItem, ActivityScope } from 'lib/components/ActivityLog/humanizeActivity'

export const featureFlagsActivityResponseJson: ActivityLogItem[] = [
    {
        user: { first_name: 'Paul', email: 'paul@posthog.com' },
        activity: 'created',
        scope: ActivityScope.FEATURE_FLAG,
        item_id: '1825',
        detail: {
            merge: null,
            changes: [],
            name: 'an_incredible_feature_flag',
        },
        created_at: '2022-03-21T16:01:54.776439Z',
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
