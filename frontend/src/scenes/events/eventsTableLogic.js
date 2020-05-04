import { kea } from 'kea'
import { fromParams, toParams } from 'lib/utils'
import { router } from 'kea-router'
import api from 'lib/api'

const addQuestion = search => (search ? `?${search}` : '')

// props: fixedFilters
export const eventsTableLogic = kea({
    actions: () => ({
        setProperties: properties => ({ properties }),
        updateProperty: (key, value) => ({ key, value }),
        fetchEvents: (nextParams = null) => ({ nextParams }),
        fetchEventsSuccess: (events, hasNext, isNext) => ({ events, hasNext, isNext }),
        fetchNextEvents: true,
        flipSort: true,
        pollEvents: true,
        setSelectedEvent: selectedEvent => ({ selectedEvent }),
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

    events: ({ actions }) => ({
        afterMount: [actions.fetchEvents],
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
        '/events': () => {
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
            // clearTimeout(this.poller)

            const urlParams = toParams({
                properties: values.properties,
                ...(props.fixedFilters || {}),
                ...(nextParams || {}),
                orderBy: [values.orderBy],
            })

            const events = await api.get('api/event/?' + urlParams)
            breakpoint()
            actions.fetchEventsSuccess(events.results, events.next, !!nextParams)
            // this.poller = setTimeout(this.pollEvents, this.pollTimeout)
        },
    }),
})
