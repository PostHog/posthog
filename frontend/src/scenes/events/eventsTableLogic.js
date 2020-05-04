import { kea } from 'kea'
import { fromParams, toParams } from 'lib/utils'
import { router } from 'kea-router'
import api from 'lib/api'

const POLL_TIMEOUT = 5000

const addQuestion = search => (search ? `?${search}` : '')

// props: fixedFilters
export const eventsTableLogic = kea({
    // Set a unique key based on the fixed filters.
    // This way if we move back/forward between /events and /person/ID, the logic is reloaded.
    key: props => (props.fixedFilters ? JSON.stringify(props.fixedFilters) : 'all'),

    actions: () => ({
        setProperties: properties => ({ properties }),
        updateProperty: (key, value) => ({ key, value }),
        fetchEvents: (nextParams = null) => ({ nextParams }),
        fetchEventsSuccess: (events, hasNext, isNext) => ({ events, hasNext, isNext }),
        fetchNextEvents: true,
        flipSort: true,
        pollEvents: true,
        pollEventsSuccess: events => ({ events }),
        prependNewEvents: events => ({ events }),
        setSelectedEvent: selectedEvent => ({ selectedEvent }),
        setPollTimeout: pollTimeout => ({ pollTimeout }),
    }),

    reducers: () => ({
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
        urlParams: [
            () => [selectors.properties],
            properties => {
                if (Object.keys(properties).length > 0) {
                    return '?' + toParams({ properties })
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
            return `${router.values.location.pathname}${values.urlParams}`
        },
        updateProperty: () => {
            return `${router.values.location.pathname}${values.urlParams}`
        },
    }),

    urlToAction: ({ actions, values }) => ({
        '*': () => {
            const { urlParams } = values
            const newFilters = fromParams()
            const newUrlParams = addQuestion(toParams(newFilters))

            if (newUrlParams !== urlParams) {
                actions.setProperties(newFilters.properties ? JSON.parse(newFilters.properties) : {})
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

            const events = await api.get('api/event/?' + urlParams)
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

            const events = await api.get('api/event/?' + toParams(params))
            breakpoint()

            actions.pollEventsSuccess(events.results)

            actions.setPollTimeout(setTimeout(actions.pollEvents, POLL_TIMEOUT))
        },
    }),
})
