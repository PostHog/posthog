import { actions, connect, events, kea, listeners, path, props, reducers, selectors } from 'kea'

import { Spinner, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { liveEventsHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { LiveEvent } from '~/types'

import type { liveEventsLogicType } from './liveEventsLogicType'

const ERROR_TOAST_ID = 'live-stream-error'

export interface LiveEventsLogicProps {
    showLiveStreamErrorToast?: boolean
}

export const liveEventsLogic = kea<liveEventsLogicType>([
    path(['scenes', 'activity', 'live-events', 'liveEventsLogic']),
    props({} as LiveEventsLogicProps),
    connect(() => ({
        values: [teamLogic, ['currentTeam']],
    })),
    actions(() => ({
        addEvents: (events: LiveEvent[]) => ({ events }),
        clearEvents: true,
        setFilters: (filters: { eventType: string | null }) => ({ filters }),
        updateEventsConnection: true,
        pauseStream: true,
        resumeStream: true,
        setClientSideFilters: (clientSideFilters: Record<string, any>) => ({ clientSideFilters }),
        addEventHost: (eventHost: string) => ({ eventHost }),
    })),
    reducers({
        events: [
            [] as LiveEvent[],
            {
                addEvents: (state, { events }) => {
                    const newState = [...events, ...state]
                    if (newState.length > 100) {
                        return newState.slice(0, 100)
                    }
                    return newState
                },
                clearEvents: () => [],
            },
        ],
        filters: [
            { eventType: null } as { eventType: string | null },
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
        clientSideFilters: [
            {} as Record<string, any>,
            {
                setClientSideFilters: (_, { clientSideFilters }) => clientSideFilters,
            },
        ],
        streamPaused: [
            false,
            {
                pauseStream: () => true,
                resumeStream: () => false,
            },
        ],
        lastBatchTimestamp: [
            null as number | null,
            {
                addEvents: (state, { events }) => {
                    if (events.length > 0) {
                        return performance.now()
                    }
                    return state
                },
            },
        ],
        eventHosts: [
            [] as string[],
            {
                addEventHost: (state, { eventHost }) => {
                    if (state.length >= 50 || state.includes(eventHost)) {
                        return state
                    }
                    return [...state, eventHost]
                },
            },
        ],
    }),
    selectors(({ selectors }) => ({
        eventCount: [() => [selectors.events], (events: LiveEvent[]) => events.length],
        filteredEvents: [
            (s) => [s.events, s.clientSideFilters],
            (events: LiveEvent[], clientSideFilters: Record<string, any>) => {
                return events.filter((event) => {
                    return Object.entries(clientSideFilters).every(([key, value]) => {
                        return key in event && event[key as keyof LiveEvent] === value
                    })
                })
            },
        ],
    })),
    listeners(({ actions, values, cache, props }) => ({
        setFilters: () => {
            actions.clearEvents()
            actions.updateEventsConnection()
        },
        updateEventsConnection: async () => {
            if (cache.eventSourceController) {
                cache.eventSourceController.abort()
            }

            if (values.streamPaused) {
                return
            }

            if (!values.currentTeam) {
                return
            }

            const { eventType } = values.filters
            const url = new URL(`${liveEventsHostOrigin()}/events`)
            if (eventType) {
                url.searchParams.append('eventType', eventType)
            }

            cache.batch = []
            cache.eventSourceController = new AbortController()

            await api.stream(url.toString(), {
                headers: {
                    Authorization: `Bearer ${values.currentTeam.live_events_token}`,
                },
                signal: cache.eventSourceController.signal,
                onMessage: (event) => {
                    lemonToast.dismiss(ERROR_TOAST_ID)
                    const eventData = JSON.parse(event.data)
                    cache.batch.push(eventData)
                    if (cache.batch.length >= 10 || performance.now() - (values.lastBatchTimestamp || 0) > 300) {
                        actions.addEvents(cache.batch)
                        cache.batch.length = 0
                    }
                },
                onError: (error) => {
                    if (!cache.hasShownLiveStreamErrorToast && props.showLiveStreamErrorToast) {
                        console.error('Failed to poll events. You likely have no events coming in.', error)
                        lemonToast.error(`No live events found. Continuing to retry in the background…`, {
                            icon: <Spinner />,
                            toastId: ERROR_TOAST_ID,
                            autoClose: false,
                        })
                        cache.hasShownLiveStreamErrorToast = true
                    }
                },
            })
        },
        pauseStream: () => {
            if (cache.eventSourceController) {
                cache.eventSourceController.abort()
            }
        },
        resumeStream: () => {
            actions.updateEventsConnection()
        },
        addEvents: ({ events }) => {
            if (events.length > 0) {
                const event = events[0]
                const eventUrl = event.properties?.$current_url
                if (eventUrl) {
                    const eventHost = new URL(eventUrl).host
                    const eventProtocol = new URL(eventUrl).protocol
                    actions.addEventHost(`${eventProtocol}//${eventHost}`)
                }
            }
        },
    })),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.updateEventsConnection()
        },
        beforeUnmount: () => {
            if (cache.eventSourceController) {
                cache.eventSourceController.abort()
            }
        },
    })),
])
