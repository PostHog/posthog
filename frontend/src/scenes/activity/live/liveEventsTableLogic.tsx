import { actions, connect, events, kea, listeners, path, props, reducers, selectors } from 'kea'

import { Spinner, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { liveEventsHostOrigin } from 'lib/utils/apiHost'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb, LiveEvent } from '~/types'

import type { liveEventsTableLogicType } from './liveEventsTableLogicType'

const ERROR_TOAST_ID = 'live-stream-error'

export interface LiveEventsTableProps {
    showLiveStreamErrorToast?: boolean
    tabId?: string
}

export const liveEventsTableLogic = kea<liveEventsTableLogicType>([
    path(['scenes', 'activity', 'live-events', 'liveEventsTableLogic']),
    tabAwareScene(),
    props({} as LiveEventsTableProps),
    connect(() => ({
        values: [teamLogic, ['currentTeam'], featureFlagLogic, ['featureFlags']],
    })),
    actions(() => ({
        addEvents: (events) => ({ events }),
        clearEvents: true,
        setFilters: (filters) => ({ filters }),
        updateEventsConnection: true,
        pauseStream: true,
        resumeStream: true,
        setCurEventProperties: (curEventProperties) => ({ curEventProperties }),
        setClientSideFilters: (clientSideFilters: Record<string, any>) => ({ clientSideFilters }),
        pollStats: true,
        setStats: (stats) => ({ stats }),
        addEventHost: (eventHost) => ({ eventHost }),
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
                    if (!state.includes(eventHost)) {
                        return [...state, eventHost]
                    }
                    return state ?? []
                },
            },
        ],
    }),
    selectors(({ selectors }) => ({
        eventCount: [() => [selectors.events], (events: any) => events.length],
        filteredEvents: [
            (s) => [s.events, s.clientSideFilters],
            (events: LiveEvent[], clientSideFilters: Record<string, any>) => {
                return events.filter((event) => {
                    return Object.entries(clientSideFilters).every(([key, value]) => {
                        return key in event && event[key] === value
                    })
                })
            },
        ],
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.LiveEvents,
                    name: 'Live',
                    iconType: 'dashboard',
                },
            ],
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
                    // If the batch is 10 or more events, or if it's been more than 300ms since the last batch
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
                        cache.hasShownLiveStreamErrorToast = true // Only show once
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
            } finally {
                cache.statsTimer = setTimeout(() => {
                    actions.pollStats()
                }, 1500)
            }
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
            actions.pollStats()
        },
        beforeUnmount: () => {
            if (cache.eventSourceController) {
                cache.eventSourceController.abort()
            }
            if (cache.statsTimer) {
                clearTimeout(cache.statsTimer)
            }
        },
    })),
])
