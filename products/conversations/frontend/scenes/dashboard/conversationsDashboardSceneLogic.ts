import { actions, kea, path, reducers } from 'kea'

export type TimeRange = '24h' | '7d' | '30d'
export type ChannelFilter = 'all' | 'widget' | 'slack' | 'email'

export const conversationsDashboardSceneLogic = kea([
    path(['products', 'conversations', 'frontend', 'scenes', 'dashboard', 'conversationsDashboardSceneLogic']),
    actions({
        setTimeRange: (timeRange: TimeRange) => ({ timeRange }),
        setChannelFilter: (channel: ChannelFilter) => ({ channel }),
    }),
    reducers({
        timeRange: [
            '24h' as TimeRange,
            {
                setTimeRange: (_, { timeRange }) => timeRange,
            },
        ],
        channelFilter: [
            'all' as ChannelFilter,
            {
                setChannelFilter: (_, { channel }) => channel,
            },
        ],
    }),
])
