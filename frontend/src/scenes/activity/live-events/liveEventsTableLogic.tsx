import { lemonToast, Spinner } from '@posthog/lemon-ui'
import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { liveEventsHostOrigin } from 'lib/utils/liveEventHost'
import { teamLogic } from 'scenes/teamLogic'

import { LiveEvent } from '~/types'

import type { liveEventsTableLogicType } from './liveEventsTableLogicType'

const ERROR_TOAST_ID = 'live-stream-error'

export const liveEventsTableLogic = kea<liveEventsTableLogicType>([
    path(['scenes', 'activity', 'live-events', 'liveEventsTableLogic']),
    connect({
        values: [teamLogic, ['currentTeam']],
    }),
    actions(() => ({
        addEvents: (events) => ({ events }),
        clearEvents: true,
        setFilters: (filters) => ({ filters }),
        updateEventsSource: (source) => ({ source }),
        updateEventsConnection: true,
        pauseStream: true,
        resumeStream: true,
        setCurEventProperties: (curEventProperties) => ({ curEventProperties }),
        setClientSideFilters: (clientSideFilters) => ({ clientSideFilters }),
        pollStats: true,
        setStats: (stats) => ({ stats }),
        showLiveStreamErrorToast: true,
    })),
    reducers({
        events: [
            [] as LiveEvent[],
            {
                addEvents: (state, { events }) => {
                    const newState = [...events, ...state]
                    if (newState.length > 500) {
                        return newState.slice(0, 400)
                    }
                    return newState
                },
                clearEvents: () => [],
            },
        ],
        filters: [
            { eventType: null },
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        clientSideFilters: [
            {},
            {
                setClientSideFilters: (_, { clientSideFilters }) => clientSideFilters,
            },
        ],
        eventsSource: [
            null as EventSource | null,
            {
                updateEventsSource: (_, { source }) => source,
            },
        ],
        streamPaused: [
            false,
            {
                pauseStream: () => true,
                resumeStream: () => false,
            },
        ],
        curEventProperties: [
            [],
            {
                setCurEventProperties: (_, { curEventProperties }) => curEventProperties,
            },
        ],
        stats: [
            { users_on_product: null },
            {
                setStats: (_, { stats }) => stats,
            },
        ],
        lastBatchTimestamp: [
            null as number | null,
            {
                addEvents: (state, { events }) => {
                    if (events.length > 0) {
                        return Date.now()
                    }
                    return state
                },
            },
        ],
    }),
    selectors(({ selectors }) => ({
        eventCount: [() => [selectors.events], (events: any) => events.length],
        filteredEvents: [
            (s) => [s.events, s.clientSideFilters],
            (events, clientSideFilters) => {
                return events.filter((event) => {
                    return Object.entries(clientSideFilters).every(([key, value]) => {
                        return event[key] === value
                    })
                })
            },
        ],
    })),
    listeners(({ actions, values, cache }) => ({
        setFilters: () => {
            actions.clearEvents()
            actions.updateEventsConnection()
        },
        updateEventsConnection: async () => {
            if (values.eventsSource) {
                values.eventsSource.close()
            }

            if (values.streamPaused) {
                return
            }

            if (!values.currentTeam) {
                return
            }

            const { eventType } = values.filters
            const url = new URL(`${liveEventsHostOrigin()}/events`)
            url.searchParams.append('teamId', values.currentTeam.id.toString())
            if (eventType) {
                url.searchParams.append('eventType', eventType)
            }

            const source = new window.EventSourcePolyfill(url.toString(), {
                headers: {
                    Authorization: `Bearer ${values.currentTeam?.live_events_token}`,
                },
            })

            const batch: Record<string, any>[] = []
            source.onmessage = function (event: any) {
                lemonToast.dismiss(ERROR_TOAST_ID)
                const eventData = JSON.parse(event.data)
                batch.push(eventData)
                // If the batch is 10 or more events, or if it's been more than 300ms since the last batch
                if (batch.length >= 10 || Date.now() - (values.lastBatchTimestamp || 0) > 300) {
                    actions.addEvents(batch)
                    batch.length = 0
                }
            }

            source.onerror = function (e) {
                console.error(e)
                if (!cache.hasShownLiveStreamErrorToast) {
                    lemonToast.error(
                        `Cannot connect to the live event stream. Continuing to retry in the background…`,
                        { icon: <Spinner />, toastId: ERROR_TOAST_ID, autoClose: false }
                    )
                    cache.hasShownLiveStreamErrorToast = true // Only show roughly once
                }
            }

            actions.updateEventsSource(source)
        },
        pauseStream: () => {
            if (values.eventsSource) {
                values.eventsSource.close()
            }
        },
        resumeStream: () => {
            actions.updateEventsConnection()
        },
        pollStats: async () => {
            try {
                if (!values.currentTeam) {
                    return
                }

                const response = await fetch(
                    `${liveEventsHostOrigin()}/stats?teamId=${values.currentTeam.id.toString()}`,
                    {
                        headers: {
                            Authorization: `Bearer ${values.currentTeam?.live_events_token}`,
                        },
                    }
                )
                const data = await response.json()
                actions.setStats(data)
            } catch (error) {
                console.error('Failed to poll stats:', error)
            }
        },
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            if (!liveEventsHostOrigin()) {
                return
            }

            actions.updateEventsConnection()
            const interval = setInterval(() => {
                actions.pollStats()
            }, 1500)
            return () => {
                if (values.eventsSource) {
                    values.eventsSource.close()
                }
                clearInterval(interval)
            }
        },
    })),
])
