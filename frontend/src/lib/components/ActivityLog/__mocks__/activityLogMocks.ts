import { ActivityScope, ActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'

export const featureFlagsActivityResponseJson: ActivityLogItem[] = [
    {
        user: { first_name: 'kunal', email: 'kunal@posthog.com' },
        activity: 'created',
        scope: ActivityScope.FEATURE_FLAG,
        item_id: '7',
        detail: {
            changes: null,
            name: 'test flag',
        },
        created_at: '2022-02-05T16:28:39.594Z',
    },
    {
        user: { first_name: 'eli', email: 'eli@posthog.com' },
        activity: 'updated',
        scope: ActivityScope.FEATURE_FLAG,
        item_id: '7',
        detail: {
            changes: [
                {
                    type: 'FeatureFlag',
                    action: 'changed',
                    field: 'name',
                    after: 'this is what was added',
                },
            ],
            name: 'test flag',
        },
        created_at: '2022-02-06T16:28:39.594Z',
    },
    {
        user: { first_name: 'guido', email: 'guido@posthog.com' },
        activity: 'updated',
        scope: ActivityScope.FEATURE_FLAG,
        item_id: '7',
        detail: {
            changes: [
                {
                    type: 'FeatureFlag',
                    action: 'changed',
                    field: 'filters',
                    after: { filter: 'info' },
                },
            ],
            name: 'test flag',
        },
        created_at: '2022-02-08T16:28:39.594Z',
    },
]
