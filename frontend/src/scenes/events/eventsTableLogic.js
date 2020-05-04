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
        fetchEvents: true,
        fetchEventsSuccess: (events, hasNext) => ({ events, hasNext }),
        fetchNextEvents: true,
        fetchNextEventsSuccess: (events, hasNext) => ({ events, hasNext }),
        pollEvents: true,
        flipSort: true,
        setEventSelected: eventSelected => ({ eventSelected }),
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
                fetchEvents: () => true,
                fetchEventsSuccess: () => false,
            },
        ],
        isLoadingNext: [
            false,
            {
                fetchNextEvents: () => true,
                fetchNextEventsSuccess: () => false,
            },
        ],
        events: [
            [],
            {
                fetchEventsSuccess: (_, { events }) => events,
                fetchNextEventsSuccess: (state, { events }) => [...state, ...events],
            },
        ],
        hasNext: [
            false,
            {
                fetchEvents: () => false,
                fetchEventsSuccess: (_, { hasNext }) => hasNext,
                fetchNextEvents: () => false,
                fetchNextEventsSuccess: (_, { hasNext }) => hasNext,
            },
        ],
        orderBy: ['-timestamp', { flipSort: state => (state === 'timestamp' ? '-timestamp' : 'timestamp') }],
        eventSelected: [
            null,
            {
                setEventSelected: (_, { eventSelected }) => eventSelected,
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
        fetchEvents: async (_, breakpoint) => {
            // clearTimeout(this.poller)

            const urlParams = toParams({
                properties: values.properties,
                ...(props.fixedFilters || {}),
                orderBy: [values.orderBy],
            })

            const events = await api.get('api/event/?' + urlParams)
            breakpoint()
            actions.fetchEventsSuccess(events.results, events.next)
            // this.poller = setTimeout(this.pollEvents, this.pollTimeout)
        },
        fetchNextEvents: async () => {
            // clearTimeout(this.poller)
            const { events } = values

            const urlParams = toParams({
                properties: values.properties,
                ...(props.fixedFilters || {}),
                [values.orderBy === 'timestamp' ? 'after' : 'before']: events[events.length - 1].timestamp,
                orderBy: [values.orderBy],
            })

            const olderEvents = await api.get('api/event/?' + urlParams)
            actions.fetchNextEventsSuccess(olderEvents.results, olderEvents.next)
            // this.poller = setTimeout(this.pollEvents, this.pollTimeout)
        },
    }),
})
