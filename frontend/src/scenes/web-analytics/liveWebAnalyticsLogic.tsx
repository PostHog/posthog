import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'

import { liveEventsHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import type { liveWebAnalyticsLogicType } from './liveWebAnalyticsLogicType'

export interface StatsResponse {
    users_on_product?: number
}
export const liveWebAnalyticsLogic = kea<liveWebAnalyticsLogicType>([
    path(['scenes', 'webAnalytics', 'liveWebAnalyticsLogic']),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions(() => ({
        pollStats: true,
        setLiveUserCount: ({ liveUserCount, now }: { liveUserCount: number; now: Date }) => ({
            liveUserCount,
            now,
        }),
        setNow: ({ now }: { now: Date }) => ({ now }),
        setIsHovering: (isHovering: boolean) => ({ isHovering }),
    })),
    reducers({
        liveUserCount: [
            null as number | null,
            {
                setLiveUserCount: (_, { liveUserCount }) => liveUserCount,
            },
        ],
        statsUpdatedTime: [
            null as Date | null,
            {
                setLiveUserCount: (_, { now }) => now,
            },
        ],
        now: [
            null as Date | null,
            {
                setNow: (_, { now }) => now,
                setLiveUserCount: (_, { now }) => now,
            },
        ],
        isHovering: [
            false,
            {
                setIsHovering: (_, { isHovering }) => isHovering,
            },
        ],
    }),
    selectors({
        liveUserUpdatedSecondsAgo: [
            (s) => [s.statsUpdatedTime, s.now],
            (statsUpdatedTime: Date | null, now: Date | null) => {
                if (!statsUpdatedTime || !now) {
                    return null
                }
                const seconds = Math.ceil((now.getTime() - statsUpdatedTime.getTime()) / 1000)
                if (seconds < 0 || seconds >= 300) {
                    // this should only happen if we have a bug, but be defensive and don't show anything surprising if there is a bug
                    return null
                }
                return seconds
            },
        ],
    }),
    listeners(({ actions, values, cache }) => ({
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
                const data: StatsResponse = await response.json()
                const liveUserCount = data.users_on_product || 0 // returns undefined if there are no users
                actions.setLiveUserCount({ liveUserCount, now: new Date() })
            } catch (error) {
                console.error('Failed to poll stats:', error)
            }
        },
        setIsHovering: ({ isHovering }) => {
            if (isHovering) {
                actions.setNow({ now: new Date() })
                cache.disposables.add(() => {
                    const intervalId = setInterval(() => {
                        actions.setNow({ now: new Date() })
                    }, 500)
                    return () => clearInterval(intervalId)
                }, 'nowInterval')
            } else {
                cache.disposables.dispose('nowInterval')
            }
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.setNow({ now: new Date() })
            actions.pollStats()

            cache.disposables.add(() => {
                const intervalId = setInterval(() => {
                    actions.pollStats()
                }, 30000)
                return () => clearInterval(intervalId)
            }, 'statsInterval')
        },
        beforeUnmount: () => {
            // Disposables handle cleanup automatically
        },
    })),
])
