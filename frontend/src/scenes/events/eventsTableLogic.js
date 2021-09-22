import { kea } from 'kea'
import { errorToast, objectsEqual, toParams } from 'lib/utils'
import { router } from 'kea-router'
import api from 'lib/api'
import dayjs from 'dayjs'
import { userLogic } from 'scenes/userLogic'
import { tableConfigLogic } from 'lib/components/ResizableTable/tableConfigLogic'

const POLL_TIMEOUT = 5000

const formatEvents = (events, newEvents, apiUrl) => {
    let eventsFormatted = []
    if (!apiUrl) {
        eventsFormatted = [...events.map((event) => ({ event }))]
    } else {
        eventsFormatted = [
            ...events.map((item) => ({
                event: { ...item.event, actionName: item.action.name, actionId: item.action.id },
            })),
        ]
    }
    eventsFormatted.forEach((event, index) => {
        if (
            index > 0 &&
            eventsFormatted[index - 1].event &&
            !dayjs(event.event.timestamp).isSame(eventsFormatted[index - 1].event.timestamp, 'day')
        ) {
            eventsFormatted.splice(index, 0, { date_break: dayjs(event.event.timestamp).format('LL') })
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
export const eventsTableLogic = kea({
    // Set a unique key based on the fixed filters.
    // This way if we move back/forward between /events and /person/ID, the logic is reloaded.
    key: (props) =>
        (props.fixedFilters ? JSON.stringify(props.fixedFilters) : 'all') +
        '-' +
        (props.apiUrl || 'events') +
        (props.live ? '-live' : '') +
        props.key,

    actions: () => ({
        setProperties: (properties) => {
            if (Array.isArray(properties) && properties.length === 0) {
                return { properties: {} }
            }
            return { properties }
        },
        setColumnConfig: (columnConfig) => ({ columnConfig }),
        setColumnConfigSaving: (saving) => ({ saving }), // Type: boolean
        fetchEvents: (nextParams = null) => ({ nextParams }),
        fetchEventsSuccess: (events, hasNext = false, isNext = false) => ({ events, hasNext, isNext }),
        fetchNextEvents: true,
        fetchOrPollFailure: (error) => ({ error }),
        flipSort: true,
        pollEvents: true,
        pollEventsSuccess: (events) => ({ events }),
        prependNewEvents: (events) => ({ events }),
        setSelectedEvent: (selectedEvent) => ({ selectedEvent }),
        setPollTimeout: (pollTimeout) => ({ pollTimeout }),
        setDelayedLoading: true,
        setEventFilter: (event) => ({ event }),
        toggleAutomaticLoad: (automaticLoadEnabled) => ({ automaticLoadEnabled }),
    }),

    reducers: () => ({
        // save the pathname that was used when this logic was mounted
        // we use it to NOT update the filters when the user moves away from this path, yet the scene is still active
        initialPathname: [(state) => router.selectors.location(state).pathname, { noop: (a) => a }],
        properties: [
            [],
            {
                setProperties: (_, { properties }) => properties,
            },
        ],
        eventFilter: [
            '',
            {
                setEventFilter: (_, { event }) => event,
            },
        ],
        isLoading: [
            false,
            {
                fetchEvents: (state, { nextParams }) => (nextParams ? state : state || null),
                setDelayedLoading: () => true,
                fetchEventsSuccess: () => false,
                fetchOrPollFailure: () => false,
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
        orderBy: ['-timestamp', { flipSort: (state) => (state === 'timestamp' ? '-timestamp' : 'timestamp') }],
        selectedEvent: [
            null,
            {
                setSelectedEvent: (_, { selectedEvent }) => selectedEvent,
            },
        ],
        newEvents: [
            [],
            {
                setProperties: () => [],
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
                    events.forEach((event) => {
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
        columnConfigSaving: [
            false,
            {
                setColumnConfigSaving: (_, { saving }) => saving,
            },
        ],
        automaticLoadEnabled: [
            false,
            {
                toggleAutomaticLoad: (_, { automaticLoadEnabled }) => automaticLoadEnabled,
            },
        ],
    }),

    selectors: ({ selectors, props }) => ({
        eventsFormatted: [
            () => [selectors.events, selectors.newEvents],
            (events, newEvents) => formatEvents(events, newEvents, props.apiUrl),
        ],
        columnConfig: [() => [userLogic.selectors.user], (user) => user?.events_column_config?.active || 'DEFAULT'],
        exportUrl: [
            () => [selectors.eventFilter, selectors.orderBy, selectors.properties],
            (eventFilter, orderBy, properties) =>
                `/api/event.csv?${toParams({
                    properties,
                    ...(props.fixedFilters || {}), // this never changes, the logic instance is keyed on this value
                    ...(eventFilter ? { event: eventFilter } : {}),
                    orderBy: [orderBy],
                })}`,
        ],
    }),

    events: ({ values }) => ({
        // No afterMount necessary because actionToUrl will call
        beforeUnmount: () => {
            clearTimeout(values.pollTimeout)
        },
    }),

    actionToUrl: ({ values }) => ({
        setProperties: () => {
            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    properties: values.properties,
                },
                router.values.hashParams,
                { replace: true },
            ]
        },
        toggleAutomaticLoad: () => {
            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    autoload: values.automaticLoadEnabled,
                },
                router.values.hashParams,
                { replace: true },
            ]
        },
    }),

    urlToAction: ({ actions, values }) => ({
        '*': (_, searchParams, hashParams) => {
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

            const isFirstRedirect = hashParams.backTo // first time we've navigated here from another page

            if (!objectsEqual(searchParams.properties || {}, values.properties) || isFirstRedirect) {
                actions.setProperties(searchParams.properties || {})
            }

            if (searchParams.autoload) {
                actions.toggleAutomaticLoad(searchParams.autoload)
            }
        },
    }),

    listeners: ({ actions, values, props }) => ({
        setColumnConfig: ({ columnConfig }) => {
            actions.setColumnConfigSaving(true)
            userLogic.actions.updateUser({ events_column_config: { active: columnConfig } })
        },
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
            async (_, breakpoint) => {
                if (values.events.length > 0) {
                    await breakpoint(500)
                }
                if (values.isLoading === null) {
                    actions.setDelayedLoading()
                }
            },
            async ({ nextParams }, breakpoint) => {
                clearTimeout(values.pollTimeout)

                const urlParams = toParams({
                    properties: values.properties,
                    ...(props.fixedFilters || {}),
                    ...(nextParams || {}),
                    ...(values.eventFilter ? { event: values.eventFilter } : {}),
                    orderBy: [values.orderBy],
                })

                let events = null

                try {
                    events = await api.get(`${props.apiUrl || 'api/event/'}?${urlParams}`)
                } catch (error) {
                    actions.fetchOrPollFailure(error)
                    return
                }

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

            let params = {
                properties: values.properties,
                ...(props.fixedFilters || {}),
                ...(values.eventFilter ? { event: values.eventFilter } : {}),
                orderBy: [values.orderBy],
            }

            const event = values.events[0]

            if (event) {
                params.after = event.timestamp || event.event.timestamp
            }

            let events = null

            try {
                events = await api.get(`${props.apiUrl || 'api/event/'}?${toParams(params)}`)
            } catch (e) {
                // We don't call fetchOrPollFailure because we don't to generate an error alert for this
                return
            }

            breakpoint()

            if (values.automaticLoadEnabled || props.live) {
                actions.prependNewEvents(events.results)
            } else {
                actions.pollEventsSuccess(events.results)
            }

            actions.setPollTimeout(setTimeout(actions.pollEvents, POLL_TIMEOUT))
        },
        fetchOrPollFailure: ({ error }) => {
            errorToast(
                undefined,
                'There was a problem fetching your events. Please refresh this page to try again.',
                error.detail,
                error.code
            )
        },
        [userLogic.actionTypes.updateUserSuccess]: () => {
            actions.setColumnConfigSaving(false)
            tableConfigLogic.actions.setState(null)
        },
        [userLogic.actionTypes.updateUserFailure]: () => {
            actions.setColumnConfigSaving(false)
        },
        toggleAutomaticLoad: ({ automaticLoadEnabled }) => {
            if (automaticLoadEnabled && values.newEvents.length > 0) {
                actions.prependNewEvents(values.newEvents)
            }
        },
    }),
})
