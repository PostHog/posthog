import { HistoryActions, HistoryListItem } from 'lib/components/HistoryList/historyListLogic'

export const featureFlagsHistoryResponseJson: HistoryListItem[] = [
    {
        email: 'kunal@posthog.com',
        name: 'kunal',
        action: HistoryActions.FEATURE_FLAG_CREATED,
        detail: {
            id: 7,
            name: 'test flag',
        },
        created_at: '2022-02-05T16:28:39.594Z',
    },
    {
        email: 'eli@posthog.com',
        name: 'eli',
        action: HistoryActions.FEATURE_FLAG_DESCRIPTION_CHANGED,
        detail: {
            id: 7,
            to: 'this is what was added',
        },
        created_at: '2022-02-06T16:28:39.594Z',
    },
    {
        email: 'guido@posthog.com',
        name: 'guido',
        action: HistoryActions.FEATURE_FLAG_FILTERS_CHANGED,
        detail: {
            id: 7,
            to: "{ 'filter': 'info' }",
        },
        created_at: '2022-02-08T16:28:39.594Z',
    },
    {
        email: 'paul@posthog.com',
        name: 'paul',
        action: HistoryActions.FEATURE_FLAG_ACTIVE_CHANGED,
        detail: {
            id: 7,
            to: false,
        },
        created_at: '2022-02-08T16:45:39.594Z',
    },
]
