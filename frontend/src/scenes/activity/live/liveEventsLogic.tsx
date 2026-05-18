import { actions, connect, events, kea, listeners, path, props, reducers, selectors } from 'kea'

import { Spinner, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { isEventPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { liveEventsHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'

import { AnyPropertyFilter, LiveEvent, PropertyOperator } from '~/types'

import { deduplicateEvents } from './deduplicateEvents'
import type { liveEventsLogicType } from './liveEventsLogicType'

const ERROR_TOAST_ID = 'live-stream-error'
const STALE_TOAST_ID = 'live-stream-stale'
// The backend emits a heartbeat event every 30s; we surface a "reconnecting"
// state if nothing (event or heartbeat) arrives within roughly two intervals.
const STREAM_STALE_TIMEOUT_MS = 65_000
const HEARTBEAT_EVENT_NAME = 'heartbeat'
const STREAM_WATCHDOG_KEY = 'streamWatchdog'

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
        setFilters: (filters: { eventType?: string | null; properties?: AnyPropertyFilter[] }) => ({ filters }),
        updateEventsConnection: true,
        pauseStream: true,
        resumeStream: true,
        setClientSideFilters: (clientSideFilters: Record<string, any>) => ({ clientSideFilters }),
        addEventHost: (eventHost: string) => ({ eventHost }),
        markStreamHealthy: true,
        markStreamStale: true,
    })),
    reducers({
        events: [
            [] as LiveEvent[],
            {
                addEvents: (state, { events }) => deduplicateEvents(state, events, 100),
                clearEvents: () => [],
            },
        ],
        filters: [
            { eventType: null, properties: [] } as { eventType: string | null; properties: AnyPropertyFilter[] },
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
        streamStale: [
            false,
            {
                markStreamHealthy: () => false,
                markStreamStale: () => true,
                pauseStream: () => false,
                setFilters: () => false,
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
        clearEvents: () => {
            cache.batch = []
        },
        updateEventsConnection: async () => {
            if (cache.eventSourceController) {
                cache.eventSourceController.abort()
            }
            cache.disposables.dispose(STREAM_WATCHDOG_KEY)

            if (values.streamPaused) {
                return
            }

            if (!values.currentTeam) {
                return
            }

            const { eventType, properties } = values.filters
            const url = new URL(`${liveEventsHostOrigin()}/events`)
            if (eventType) {
                url.searchParams.append('eventType', eventType)
            }
            for (const pf of properties ?? []) {
                if (!isEventPropertyFilter(pf) || pf.operator !== PropertyOperator.Exact || !pf.key) {
                    continue
                }
                const vals = Array.isArray(pf.value) ? pf.value : [pf.value]
                for (const v of vals) {
                    if (v == null) {
                        continue
                    }
                    url.searchParams.append('property', `${pf.key}=${String(v)}`)
                }
            }
            url.searchParams.append('columns', '$current_url,$screen_name')

            cache.batch = []
            cache.eventSourceController = new AbortController()

            await api.stream(url.toString(), {
                headers: {
                    Authorization: `Bearer ${values.currentTeam.live_events_token}`,
                },
                signal: cache.eventSourceController.signal,
                onMessage: (event) => {
                    // Any message — including the periodic heartbeat — proves the SSE pipe is alive.
                    // Clear the error latch so a future failure can surface a fresh toast, and
                    // re-arm the watchdog timer with a 65s budget (slightly above the 30s server interval).
                    cache.hasShownLiveStreamErrorToast = false
                    lemonToast.dismiss(ERROR_TOAST_ID)
                    actions.markStreamHealthy()
                    cache.disposables.add(() => {
                        const timerId = setTimeout(() => {
                            actions.markStreamStale()
                        }, STREAM_STALE_TIMEOUT_MS)
                        return () => clearTimeout(timerId)
                    }, STREAM_WATCHDOG_KEY)

                    if (event.event === HEARTBEAT_EVENT_NAME) {
                        return
                    }
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
        markStreamHealthy: () => {
            lemonToast.dismiss(STALE_TOAST_ID)
        },
        markStreamStale: () => {
            if (props.showLiveStreamErrorToast) {
                lemonToast.warning('Live event stream went quiet. Reconnecting…', {
                    icon: <Spinner />,
                    toastId: STALE_TOAST_ID,
                    autoClose: false,
                })
            }
            // Tear down the current connection and re-establish so a half-open SSE socket
            // (proxy dropped the TCP connection without notifying the client) is replaced.
            actions.updateEventsConnection()
        },
        pauseStream: () => {
            if (cache.eventSourceController) {
                cache.eventSourceController.abort()
            }
            cache.disposables.dispose(STREAM_WATCHDOG_KEY)
            lemonToast.dismiss(STALE_TOAST_ID)
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
            lemonToast.dismiss(ERROR_TOAST_ID)
            lemonToast.dismiss(STALE_TOAST_ID)
        },
    })),
])
