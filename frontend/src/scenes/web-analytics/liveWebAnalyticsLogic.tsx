import { actions, connect, events, kea, listeners, path, reducers } from 'kea'
import { liveEventsHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

export const liveEventsTableLogic = kea<liveEventsTableLogicType>([
    path(['scenes', 'activity', 'live-events', 'liveEventsTableLogic']),
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    actions(() => ({
        pollStats: true,
        setStats: (stats) => ({ stats }),
    })),
    reducers({
        stats: [
            { users_on_product: null },
            {
                setStats: (_, { stats }) => stats,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        pollStats: async () => {
            try {
                if (!values.currentTeam) {
                    return
                }

                const response = await fetch(`${liveEventsHostOrigin()}/stats`, {
                    headers: {
                        Authorization: `Bearer ${values.currentTeam.live_events_token}`,
                    },
                })
                const data = await response.json()
                actions.setStats(data)
            } catch (error) {
                console.error('Failed to poll stats:', error)
            }
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            cache.statsInterval = setInterval(() => {
                actions.pollStats()
            }, 1500)
        },
        beforeUnmount: () => {
            if (cache.statsInterval) {
                clearInterval(cache.statsInterval)
            }
        },
    })),
])
