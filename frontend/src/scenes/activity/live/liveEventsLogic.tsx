import { actions, connect, events, kea, listeners, path, props, reducers, selectors } from 'kea'

import { Spinner, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { isEventPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { liveEventsHostOrigin } from 'lib/utils/apiHost'
import { isOperatorFlag } from 'lib/utils/operators'
import { teamLogic } from 'scenes/teamLogic'

import { AnyPropertyFilter, LiveEvent, PropertyFilterValue, PropertyOperator } from '~/types'

import { deduplicateEvents } from './deduplicateEvents'
import type { liveEventsLogicType } from './liveEventsLogicType'

const ERROR_TOAST_ID = 'live-stream-error'

export const LIVE_EVENTS_SUPPORTED_OPERATORS: PropertyOperator[] = [
    PropertyOperator.Exact,
    PropertyOperator.IsNot,
    PropertyOperator.IContains,
    PropertyOperator.NotIContains,
    PropertyOperator.Regex,
    PropertyOperator.NotRegex,
    PropertyOperator.GreaterThan,
    PropertyOperator.GreaterThanOrEqual,
    PropertyOperator.LessThan,
    PropertyOperator.LessThanOrEqual,
    PropertyOperator.IsSet,
    PropertyOperator.IsNotSet,
]

export interface LiveEventsLogicProps {
    showLiveStreamErrorToast?: boolean
}

export const liveEventsLogic = kea<liveEventsLogicType>([
    path(['scenes', 'activity', 'live-events', 'liveEventsLogic']),
    props({} as LiveEventsLogicProps),
    connect(() => ({
        values: [teamLogic, ['currentTeam'], featureFlagLogic, ['featureFlags']],
        actions: [teamLogic, ['loadCurrentTeam']],
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
        updateEventsConnection: () => {
            cache.disposables.dispose('eventsConnection')

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
            if (values.featureFlags[FEATURE_FLAGS.LIVE_EVENTS_RICH_FILTERS]) {
                const richFilters: { key: string; operator: PropertyOperator; value?: PropertyFilterValue }[] = []
                for (const pf of properties ?? []) {
                    if (!isEventPropertyFilter(pf) || !pf.key || !pf.operator) {
                        continue
                    }
                    if (!LIVE_EVENTS_SUPPORTED_OPERATORS.includes(pf.operator)) {
                        continue
                    }
                    if (isOperatorFlag(pf.operator)) {
                        richFilters.push({ key: pf.key, operator: pf.operator })
                        continue
                    }
                    if (pf.value == null) {
                        continue
                    }
                    if (Array.isArray(pf.value)) {
                        const cleaned = pf.value.filter((v) => v != null)
                        if (cleaned.length === 0) {
                            continue
                        }
                        richFilters.push({ key: pf.key, operator: pf.operator, value: cleaned })
                    } else {
                        richFilters.push({ key: pf.key, operator: pf.operator, value: pf.value })
                    }
                }
                if (richFilters.length > 0) {
                    url.searchParams.append('properties', JSON.stringify(richFilters))
                }
            } else {
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
            }
            url.searchParams.append('columns', '$current_url,$screen_name')

            // Managed as a disposable so the long-lived streaming Response is aborted when
            // the tab is hidden and reopened on visibilitychange — an open stream on an idle
            // background tab accumulates off-heap in Blink's partition_alloc/buffer.
            cache.disposables.add(() => {
                cache.batch = []
                const controller = new AbortController()
                void api.stream(url.toString(), {
                    headers: {
                        Authorization: `Bearer ${values.currentTeam?.live_events_token}`,
                    },
                    signal: controller.signal,
                    onMessage: (event) => {
                        lemonToast.dismiss(ERROR_TOAST_ID)
                        let eventData: LiveEvent
                        try {
                            eventData = JSON.parse(event.data)
                        } catch {
                            // Drop malformed stream payloads rather than throwing inside the listener
                            return
                        }
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
                return () => controller.abort()
            }, 'eventsConnection')
        },
        pauseStream: () => {
            cache.disposables.dispose('eventsConnection')
        },
        resumeStream: () => {
            actions.updateEventsConnection()
        },
        addEvents: ({ events }) => {
            if (events.length > 0) {
                const event = events[0]
                const eventUrl = event.properties?.$current_url
                if (eventUrl) {
                    // Live events can carry a malformed `$current_url`; skip host extraction rather than throw.
                    try {
                        const parsedUrl = new URL(eventUrl)
                        actions.addEventHost(`${parsedUrl.protocol}//${parsedUrl.host}`)
                    } catch {
                        // Ignore unparseable URLs
                    }
                }
                // The team's `ingested_event` flag is flipped server-side when the first event is
                // processed, but only reaches the frontend on the next ~30s team refresh. Refresh
                // immediately when we observe a live event so banners that depend on the flag
                // (e.g. the "no events yet" project notice) can't contradict the on-screen feed.
                if (values.currentTeam && !values.currentTeam.ingested_event) {
                    actions.loadCurrentTeam()
                }
            }
        },
    })),
    events(({ actions }) => ({
        afterMount: () => {
            actions.updateEventsConnection()
        },
    })),
])
