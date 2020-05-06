import { kea } from 'kea'
import { objectsEqual, toParams } from 'lib/utils'
import { router } from 'kea-router'
import api from 'lib/api'

const POLL_TIMEOUT = 5000

// props:
// - fixedFilters
// - apiUrl = 'api/event/'
// - live = false
export const eventsTableLogic = kea({
    // Set a unique key based on the fixed filters.
    // This way if we move back/forward between /events and /person/ID, the logic is reloaded.
    key: props =>
        (props.fixedFilters ? JSON.stringify(props.fixedFilters) : 'all') +
        '-' +
        (props.apiUrl || 'events') +
        (props.live ? '-live' : ''),

    actions: () => ({
        setProperties: properties => ({ properties }),
        updateProperty: (key, value) => ({ key, value }),
        fetchEvents: (nextParams = null) => ({ nextParams }),
        fetchEventsSuccess: (events, hasNext = false, isNext = false) => ({ events, hasNext, isNext }),
        fetchNextEvents: true,
        flipSort: true,
        pollEvents: true,
        pollEventsSuccess: events => ({ events }),
        prependNewEvents: events => ({ events }),
        setSelectedEvent: selectedEvent => ({ selectedEvent }),
        setPollTimeout: pollTimeout => ({ pollTimeout }),
    }),

    reducers: () => ({
        // save the pathname that was used when this logic was mounted
        // we use it to NOT update the filters when the user moves away from this path, yet the scene is still active
        initialPathname: [state => router.selectors.location(state).pathname, { noop: a => a }],
        properties: [
            {},
            {
                setProperties: (_, { properties }) => properties,
                updateProperty: (state, { key, value }) => ({ ...state, [key]: value }),
            },
        ],
        isLoading: [
            false,
            {
                fetchEvents: (state, { nextParams }) => (nextParams ? state : true),
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
            [],
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
        orderBy: ['-timestamp', { flipSort: state => (state === 'timestamp' ? '-timestamp' : 'timestamp') }],
        selectedEvent: [
            null,
            {
                setSelectedEvent: (_, { selectedEvent }) => selectedEvent,
            },
        ],
        newEvents: [
            [],
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
                    const highlightEvents = {}
                    events.forEach(event => {
                        highlightEvents[event.id] = true
                    })
                    return highlightEvents
                },
            },
        ],
        pollTimeout: [
            null,
            {
                setPollTimeout: (_, { pollTimeout }) => pollTimeout,
            },
        ],
    }),

    selectors: ({ selectors }) => ({
        propertiesForUrl: [
            () => [selectors.properties],
            properties => {
                if (Object.keys(properties).length > 0) {
                    return { properties }
                } else {
                    return ''
                }
            },
        ],
    }),

    events: ({ actions, values }) => ({
        afterMount: [actions.fetchEvents],
        beforeUnmount: () => {
            clearTimeout(values.pollTimeout)
        },
    }),

    actionToUrl: ({ values }) => ({
        setProperties: () => {
            return [router.values.location.pathname, values.propertiesForUrl]
        },
        updateProperty: () => {
            return [router.values.location.pathname, values.propertiesForUrl]
        },
    }),

    urlToAction: ({ actions, values }) => ({
        '*': (_, searchParams) => {
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

            if (!objectsEqual(searchParams.properties || {}, values.properties)) {
                actions.setProperties(searchParams.properties || {})
            }
        },
    }),

    listeners: ({ actions, values, props }) => ({
        setProperties: () => {
            actions.fetchEvents()
        },
        updateProperty: () => {
            actions.fetchEvents()
        },
        flipSort: () => {
            actions.fetchEvents()
        },
        fetchNextEvents: async () => {
            const { events, orderBy } = values

            actions.fetchEvents({
                [orderBy === 'timestamp' ? 'after' : 'before']: events[events.length - 1].timestamp,
            })
        },
        fetchEvents: async ({ nextParams }, breakpoint) => {
            clearTimeout(values.pollTimeout)

            const urlParams = toParams({
                properties: values.properties,
                ...(props.fixedFilters || {}),
                ...(nextParams || {}),
                orderBy: [values.orderBy],
            })

            const events = await api.get(`${props.apiUrl || 'api/event/'}?${urlParams}`)
            breakpoint()
            actions.fetchEventsSuccess(events.results, events.next, !!nextParams)

            actions.setPollTimeout(setTimeout(actions.pollEvents, POLL_TIMEOUT))
        },
        pollEvents: async (_, breakpoint) => {
            // Poll events when they are ordered in ascending order based on timestamp
            if (values.orderBy !== '-timestamp') {
                return
            }

            let params = {
                properties: values.properties,
                ...(props.fixedFilters || {}),
                orderBy: [values.orderBy],
            }

            const event = values.events[0]

            if (event) {
                params.after = event.timestamp || event.event.timestamp
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
