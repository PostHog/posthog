import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import { liveEventsHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import type { liveUserCountLogicType } from './liveUserCountLogicType'

export interface LiveUserCountStats {
    users_on_product?: number
    active_recordings?: number
}

export interface LiveUserCountLogicProps {
    pollIntervalMs?: number
}

export const liveUserCountLogic = kea<liveUserCountLogicType>([
    path((key) => ['lib', 'components', 'LiveUserCount', 'liveUserCountLogic', key]),
    key((props) => props.pollIntervalMs ?? 30000),
    props({ pollIntervalMs: 30000 } as LiveUserCountLogicProps),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
        actions: [teamLogic, ['loadCurrentTeamSuccess']],
    })),
    actions(() => ({
        pollStats: true,
        setStats: (stats: LiveUserCountStats, now: Date) => ({ stats, now }),
        clearStats: true,
        setNow: (now: Date) => ({ now }),
        setIsHovering: (isHovering: boolean) => ({ isHovering }),
        pauseStream: true,
        resumeStream: true,
    })),
    reducers({
        stats: [
            null as LiveUserCountStats | null,
            {
                setStats: (_, { stats }) => stats,
                clearStats: () => null,
            },
        ],
        statsUpdatedTime: [
            null as Date | null,
            {
                setStats: (_, { now }) => now,
                clearStats: () => null,
            },
        ],
        now: [
            null as Date | null,
            {
                setNow: (_, { now }) => now,
                setStats: (_, { now }) => now,
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
        liveUserCount: [(s) => [s.stats], (stats) => stats?.users_on_product ?? null],
        activeRecordings: [(s) => [s.stats], (stats) => stats?.active_recordings ?? null],
        statsUpdatedSecondsAgo: [
            (s) => [s.statsUpdatedTime, s.now],
            (statsUpdatedTime: Date | null, now: Date | null) => {
                if (!statsUpdatedTime || !now) {
                    return null
                }
                const seconds = Math.ceil((now.getTime() - statsUpdatedTime.getTime()) / 1000)
                if (seconds < 0 || seconds >= 300) {
                    return null
                }
                return seconds
            },
        ],
    }),
    listeners(({ actions, values, cache, props }) => ({
        pollStats: async () => {
            try {
                const team = values.currentTeam
                if (!team) {
                    return
                }

                const response = await fetch(`${liveEventsHostOrigin()}/stats`, {
                    headers: {
                        Authorization: `Bearer ${team.live_events_token}`,
                    },
                })
                if (!response.ok) {
                    throw new Error(`Live user count request failed with status ${response.status}`)
                }
                const data: LiveUserCountStats = await response.json()
                if (
                    values.currentTeam?.id !== team.id ||
                    values.currentTeam.live_events_token !== team.live_events_token
                ) {
                    return
                }
                actions.setStats(data, new Date())
            } catch (error) {
                console.error('Failed to poll stats:', error)
            }
        },
        loadCurrentTeamSuccess: () => {
            actions.clearStats()
            actions.pollStats()
        },
        setIsHovering: ({ isHovering }) => {
            if (isHovering) {
                actions.setNow(new Date())
                cache.disposables.add(() => {
                    const intervalId = setInterval(() => {
                        actions.setNow(new Date())
                    }, 500)
                    return () => clearInterval(intervalId)
                }, 'nowInterval')
            } else {
                cache.disposables.dispose('nowInterval')
            }
        },
        pauseStream: () => {
            cache.disposables.dispose('statsInterval')
        },
        resumeStream: () => {
            actions.pollStats()
            cache.disposables.add(() => {
                const intervalId = setInterval(() => {
                    actions.pollStats()
                }, props.pollIntervalMs ?? 30000)
                return () => clearInterval(intervalId)
            }, 'statsInterval')
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.setNow(new Date())
            actions.resumeStream()
        },
    })),
])
