import { kea } from 'kea'
import { objectsEqual, toParams } from 'lib/utils'
import { router } from 'kea-router'
import api from 'lib/api'
import moment from 'moment'
import { eventsTableLogicType } from './eventsTableLogicType'
import { EventType, PropertyFilter } from '~/types'

const POLL_TIMEOUT = 5000

interface FormattedEventType {
    event: EventType
}

interface DateBreakRow {
    date_break: string
}

interface NewEventsRow {
    new_events: boolean
}

type EventRowType = FormattedEventType | DateBreakRow | NewEventsRow

const formatEvents = (events: EventType[], newEvents: EventType[], apiUrl?: string): EventRowType[] => {
    let eventsFormatted: EventRowType[] = []
    if (!apiUrl) {
        eventsFormatted = [...events.map((event) => ({ event }))]
    } else {
        eventsFormatted = [
            ...events.map((item) => ({
                event: item,
            })),
        ]
    }
    eventsFormatted.forEach((event, index) => {
        const prevItem = eventsFormatted[index - 1]
        if (
            index > 0 &&
            prevItem &&
            'event' in prevItem &&
            'event' in event &&
            !moment(event.event.timestamp).isSame(prevItem.event.timestamp, 'day')
        ) {
            eventsFormatted.splice(index, 0, { date_break: moment(event.event.timestamp).format('LL') })
        }
    })
    if (newEvents.length > 0) {
        eventsFormatted.splice(0, 0, { new_events: true })
    }

    return eventsFormatted
}
// props:
// - fixedFilters
// - apiUrl = 'api/event/'
// - live = false
export const eventsTableLogic = kea<eventsTableLogicType<PropertyFilter, EventType, EventRowType>>({
    // Set a unique key based on the fixed filters.
    // This way if we move back/forward between /events and /person/ID, the logic is reloaded.
    key: (props) =>
        (props.fixedFilters ? JSON.stringify(props.fixedFilters) : 'all') +
        '-' +
        (props.apiUrl || 'events') +
        (props.live ? '-live' : '') +
        props.key,

    actions: () => ({
        setProperties: (properties) => ({ properties }),
        fetchEvents: (nextParams = null) => ({ nextParams }),
        fetchEventsSuccess: (events, hasNext = false, isNext = false) => ({ events, hasNext, isNext }),
        fetchNextEvents: true,
        flipSort: true,
        pollEvents: true,
        pollEventsSuccess: (events) => ({ events }),
        prependNewEvents: (events) => ({ events }),
        setSelectedEvent: (selectedEvent) => ({ selectedEvent }),
        setPollTimeout: (pollTimeout) => ({ pollTimeout }),
        setDelayedLoading: true,
        setEventFilter: (event) => ({ event }),
    }),

    reducers: () => ({
        // save the pathname that was used when this logic was mounted
        // we use it to NOT update the filters when the user moves away from this path, yet the scene is still active
        initialPathname: [
            (((state: Record<string, any>) => router.selectors.location(state).pathname) as unknown) as string,
            { noop: (a) => a },
        ],
        properties: [
            [] as PropertyFilter[],
            {
                setProperties: (_, { properties }) => properties,
            },
        ],
        eventFilter: [
            false,
            {
                setEventFilter: (_, { event }) => event,
            },
        ],
        isLoading: [
            false,
            {
                fetchEvents: (state, { nextParams }) => (nextParams ? state : state || false),
                setDelayedLoading: () => true,
                fetchEventsSuccess: () => false,
            },
        ],
        isLoadingNext: [
            false,
            {
                fetchNextEvents: () => true,
                fetchEventsSuccess: () => false,
            },
        ],
        events: [
            [] as EventType[],
            {
                fetchEventsSuccess: (state, { events, isNext }) => (isNext ? [...state, ...events] : events),
                prependNewEvents: (state, { events }) => [...events, ...state],
            },
        ],

        hasNext: [
            false,
            {
                fetchEvents: () => false,
                fetchNextEvents: () => false,
                fetchEventsSuccess: (_, { hasNext }) => hasNext,
            },
        ],
        orderBy: ['-timestamp', { flipSort: (state) => (state === 'timestamp' ? '-timestamp' : 'timestamp') }],
        selectedEvent: [
            null,
            {
                setSelectedEvent: (_, { selectedEvent }) => selectedEvent,
            },
        ],
        newEvents: [
            [] as EventType[],
            {
                pollEventsSuccess: (_, { events }) => events,
                prependNewEvents: () => [],
            },
        ],
        highlightEvents: [
            {},
            {
                pollEventsSuccess: () => ({}),
                prependNewEvents: (_, { events }) => {
                    const highlightEvents: Record<string, boolean> = {}
                    events.forEach((event: EventType) => {
                        highlightEvents[event.id] = true
                    })
                    return highlightEvents
                },
            },
        ],
        pollTimeout: [
            null as NodeJS.Timeout | null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
    }),

    selectors: ({ selectors, props }) => ({
        propertiesForUrl: [
            () => [selectors.properties],
            (properties) => {
                if (Object.keys(properties).length > 0) {
                    return { properties }
                } else {
                    return ''
                }
            },
        ],
        eventsFormatted: [
            () => [selectors.events, selectors.newEvents],
            (events, newEvents) => formatEvents(events, newEvents, props.apiUrl as string | undefined),
        ],
    }),

    events: ({ values }) => ({
        // No afterMount necessary because actionToUrl will call
        beforeUnmount: () => {
            values.pollTimeout && clearTimeout(values.pollTimeout)
        },
    }),

    actionToUrl: ({ values }) => ({
        setProperties: () => {
            return [router.values.location.pathname, values.propertiesForUrl, window.location.hash]
        },
    }),

    urlToAction: ({ actions, values }) => ({
        '*': ({}, searchParams: Record<string, any>) => {
            try {
                // if the url changed, but we are not anymore on the page we were at when the logic was mounted
                if (router.values.location.pathname !== values.initialPathname) {
                    return
                }
            } catch (error) {
                // since this is a catch-all route, this code might run during or after the logic was unmounted
                // if we have an error accessing the filter value, the logic is gone and we should return
                return
            }

            if (
                !objectsEqual(searchParams?.properties, []) &&
                !objectsEqual(searchParams.properties || {}, values.properties)
            ) {
                actions.setProperties(searchParams.properties || {})
            }
        },
    }),

    listeners: ({ actions, values, props }) => ({
        setProperties: () => actions.fetchEvents(),
        flipSort: () => actions.fetchEvents(),
        setEventFilter: () => actions.fetchEvents(),
        fetchNextEvents: async () => {
            const { events, orderBy } = values

            actions.fetchEvents({
                [orderBy === 'timestamp' ? 'after' : 'before']: events[events.length - 1].timestamp,
            })
        },
        fetchEvents: [
            async ({}, breakpoint: (timeout: number) => void) => {
                if (values.events.length > 0) {
                    await breakpoint(500)
                }
                if (values.isLoading === null) {
                    actions.setDelayedLoading()
                }
            },
            async ({ nextParams }: { nextParams: { before: string } }, breakpoint: () => void) => {
                values.pollTimeout && clearTimeout(values.pollTimeout)

                const urlParams = toParams({
                    properties: values.properties,
                    ...((props.fixedFilters as Record<string, any>) || {}),
                    ...(nextParams || {}),
                    ...(values.eventFilter ? { event: values.eventFilter } : {}),
                    orderBy: [values.orderBy],
                })

                const events = await api.get(`${props.apiUrl || 'api/event/'}?${urlParams}`)
                breakpoint()
                actions.fetchEventsSuccess(events.results, events.next, !!nextParams)

                actions.setPollTimeout(setTimeout(actions.pollEvents, POLL_TIMEOUT))
            },
        ],
        pollEvents: async (_, breakpoint) => {
            // Poll events when they are ordered in ascending order based on timestamp
            if (values.orderBy !== '-timestamp') {
                return
            }

            const params: Record<string, any> = {
                properties: values.properties,
                ...((props.fixedFilters as Record<string, any>) || {}),
                ...(values.eventFilter ? { event: values.eventFilter } : {}),
                orderBy: [values.orderBy],
            }

            const event = values.events[0]

            if (event) {
                params.after = event.timestamp
            }

            const events = await api.get(`${props.apiUrl || 'api/event/'}?${toParams(params)}`)
            breakpoint()

            if (props.live) {
                actions.prependNewEvents(events.results)
            } else {
                actions.pollEventsSuccess(events.results)
            }

            actions.setPollTimeout(setTimeout(actions.pollEvents, POLL_TIMEOUT))
        },
    }),
})
