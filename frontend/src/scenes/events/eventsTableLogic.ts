import { kea } from 'kea'
import { errorToast, successToast, toParams } from 'lib/utils'
import { router } from 'kea-router'
import api from 'lib/api'
import { eventsTableLogicType } from './eventsTableLogicType'
import { FixedFilters } from 'scenes/events/EventsTable'
import { AnyPropertyFilter, EventsTableRowItem, EventType, PropertyFilter } from '~/types'
import { isValidPropertyFilter } from 'lib/components/PropertyFilters/utils'
import { teamLogic } from '../teamLogic'
import { urls } from 'scenes/urls'
import { dayjs } from 'lib/dayjs'

const POLL_TIMEOUT = 5000

const formatEvents = (events: EventType[], newEvents: EventType[]): EventsTableRowItem[] => {
    let eventsFormatted: EventsTableRowItem[] = []

    eventsFormatted = events.map((item) => ({
        event: item,
    }))
    eventsFormatted.forEach((event, index) => {
        const previous = eventsFormatted[index - 1]
        if (
            index > 0 &&
            event.event &&
            previous.event &&
            !dayjs(event.event.timestamp).isSame(previous.event.timestamp, 'day')
        ) {
            eventsFormatted.splice(index, 0, { date_break: dayjs(event.event.timestamp).format('LL') })
        }
    })
    if (newEvents.length > 0) {
        eventsFormatted.splice(0, 0, { new_events: true })
    }
    return eventsFormatted
}

export interface EventsTableLogicProps {
    fixedFilters?: FixedFilters
    key?: string
    sceneUrl: string
}

export interface OnFetchEventsSuccess {
    events: EventType[]
    hasNext: boolean
    isNext: boolean
}

//from visual inspection of lib/api.js
//we aren't throwing JS Errors
export interface ApiError {
    status?: string
    statusText?: string
}

export const eventsTableLogic = kea<eventsTableLogicType<ApiError, EventsTableLogicProps, OnFetchEventsSuccess>>({
    path: (key) => ['scenes', 'events', 'eventsTableLogic', key],
    props: {} as EventsTableLogicProps,
    // Set a unique key based on the fixed filters.
    // This way if we move back/forward between /events and /person/ID, the logic is reloaded.
    key: (props) =>
        [props.fixedFilters ? JSON.stringify(props.fixedFilters) : 'all', props.key, props.sceneUrl]
            .filter((keyPart) => !!keyPart)
            .join('-'),
    connect: {
        values: [teamLogic, ['currentTeamId']],
    },
    actions: {
        setProperties: (
            properties: AnyPropertyFilter[] | AnyPropertyFilter
        ): {
            properties: AnyPropertyFilter[]
        } => {
            // there seem to be multiple representations of "empty" properties
            // the page does not work with some of those representations
            // this action normalises them
            if (Array.isArray(properties)) {
                if (properties.length === 0) {
                    return { properties: [{}] }
                } else {
                    return { properties }
                }
            } else {
                return { properties: [properties] }
            }
        },
        fetchEvents: (nextParams = null) => ({ nextParams }),
        fetchEventsSuccess: (apiResponse: OnFetchEventsSuccess) => apiResponse,
        fetchNextEvents: true,
        fetchOrPollFailure: (error: ApiError) => ({ error }),
        flipSort: true,
        pollEvents: true,
        pollEventsSuccess: (events: EventType[]) => ({ events }),
        prependEvents: (events: EventType[]) => ({ events }),
        prependNewEvents: true,
        setSelectedEvent: (selectedEvent: EventType) => ({ selectedEvent }),
        setPollTimeout: (pollTimeout: number) => ({ pollTimeout }),
        setDelayedLoading: true,
        setEventFilter: (event: string) => ({ event }),
        toggleAutomaticLoad: (automaticLoadEnabled: boolean) => ({ automaticLoadEnabled }),
        noop: (s) => s,
        startDownload: true,
    },

    reducers: ({ props }) => ({
        sceneIsEventsPage: [props.sceneUrl ? props.sceneUrl === urls.events() : false, {}],
        properties: [
            [] as PropertyFilter[],
            {
                setProperties: (_, { properties }) => properties.filter(isValidPropertyFilter),
            },
        ],
        eventFilter: [
            '',
            {
                setEventFilter: (_, { event }) => event,
            },
        ],
        isLoading: [
            true,
            {
                fetchEvents: () => true,
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
            [] as EventType[],
            {
                fetchEventsSuccess: (state, { events, isNext }: OnFetchEventsSuccess) =>
                    isNext ? [...state, ...events] : events,
                prependEvents: (state, { events }) => [...events, ...state],
            },
        ],

        hasNext: [
            false,
            {
                fetchEvents: () => false,
                fetchNextEvents: () => false,
                fetchEventsSuccess: (_, { hasNext }: OnFetchEventsSuccess) => hasNext,
            },
        ],
        orderBy: ['-timestamp', { flipSort: (state) => (state === 'timestamp' ? '-timestamp' : 'timestamp') }],
        selectedEvent: [
            null as unknown as EventType,
            {
                setSelectedEvent: (_, { selectedEvent }) => selectedEvent,
            },
        ],
        newEvents: [
            [] as EventType[],
            {
                setProperties: () => [],
                pollEventsSuccess: (_, { events }) => events || [],
                prependEvents: () => [],
            },
        ],
        highlightEvents: [
            {} as Record<string, boolean>,
            {
                prependEvents: (_: Record<string, boolean>, { events }) => {
                    return events.reduce((highlightEvents, event) => {
                        highlightEvents[event.id] = true
                        return highlightEvents
                    }, {} as Record<string, boolean>)
                },
            },
        ],
        pollTimeout: [
            0,
            {
                setPollTimeout: (_, payload) => payload.pollTimeout,
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
            (events, newEvents) => formatEvents(events, newEvents),
        ],
        exportUrl: [
            () => [selectors.currentTeamId, selectors.eventFilter, selectors.orderBy, selectors.properties],
            (teamId, eventFilter, orderBy, properties) =>
                `/api/projects/${teamId}/events.csv?${toParams({
                    ...(props.fixedFilters || {}),
                    properties: [...properties, ...(props.fixedFilters?.properties || [])],
                    ...(eventFilter ? { event: eventFilter } : {}),
                    orderBy: [orderBy],
                })}`,
        ],
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
        setEventFilter: () => {
            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    eventFilter: values.eventFilter,
                },
                router.values.hashParams,
                { replace: true },
            ]
        },
    }),

    urlToAction: ({ actions, values, props }) => ({
        [props.sceneUrl]: (_: Record<string, any>, searchParams: Record<string, any>): void => {
            actions.setProperties(searchParams.properties || values.properties || {})

            if (searchParams.autoload) {
                actions.toggleAutomaticLoad(searchParams.autoload)
            }

            if (searchParams.eventFilter) {
                actions.setEventFilter(searchParams.eventFilter)
            }
        },
    }),

    events: ({ values }) => ({
        beforeUnmount: () => clearTimeout(values.pollTimeout || undefined),
    }),

    listeners: ({ actions, values, props }) => ({
        startDownload: () => {
            successToast('The export is starting', 'It should finish soon.')
            window.location.href = values.exportUrl
        },
        setProperties: () => actions.fetchEvents(),
        flipSort: () => actions.fetchEvents(),
        setEventFilter: () => actions.fetchEvents(),
        fetchNextEvents: async () => {
            const { events, orderBy } = values

            if (events.length === 0) {
                actions.fetchEvents()
            } else {
                actions.fetchEvents({
                    [orderBy === 'timestamp' ? 'after' : 'before']: events[events.length - 1].timestamp,
                })
            }
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
                    ...(props.fixedFilters || {}),
                    properties: [...values.properties, ...(props.fixedFilters?.properties || [])],
                    ...(nextParams || {}),
                    ...(values.eventFilter ? { event: values.eventFilter } : {}),
                    orderBy: [values.orderBy],
                })
                let apiResponse = null

                try {
                    apiResponse = await api.get(`api/projects/${values.currentTeamId}/events/?${urlParams}`)
                } catch (error) {
                    actions.fetchOrPollFailure(error)
                    return
                }

                breakpoint()
                actions.fetchEventsSuccess({
                    events: apiResponse.results,
                    hasNext: !!apiResponse.next,
                    isNext: !!nextParams,
                })

                // uses window setTimeout because typegen had a hard time with NodeJS.Timeout
                const timeout = window.setTimeout(actions.pollEvents, POLL_TIMEOUT)
                actions.setPollTimeout(timeout)
            },
        ],
        pollEvents: async (_, breakpoint) => {
            // Poll events when they are ordered in ascending order based on timestamp
            if (values.orderBy !== '-timestamp') {
                return
            }
            // Do not poll if the scene is in the background
            if (props.sceneUrl !== router.values.location.pathname) {
                return
            }

            const params: Record<string, unknown> = {
                ...(props.fixedFilters || {}),
                properties: [...values.properties, ...(props.fixedFilters?.properties || [])],
                ...(values.eventFilter ? { event: values.eventFilter } : {}),
                orderBy: [values.orderBy],
            }

            const event = values.events[0]

            if (event && event.timestamp) {
                params.after = event.timestamp
            }

            const urlParams = toParams(params)

            let apiResponse = null
            try {
                apiResponse = await api.get(`api/projects/${values.currentTeamId}/events/?${urlParams}`)
            } catch (e) {
                // We don't call fetchOrPollFailure because we don't to generate an error alert for this
                return
            }

            breakpoint()

            if (values.automaticLoadEnabled) {
                actions.prependEvents(apiResponse.results)
            } else {
                actions.pollEventsSuccess(apiResponse.results)
            }

            // uses window setTimeout because typegen had a hard time with NodeJS.Timeout
            const timeout = window.setTimeout(actions.pollEvents, POLL_TIMEOUT)
            actions.setPollTimeout(timeout)
        },
        prependNewEvents: () => {
            if (values.newEvents.length) {
                actions.prependEvents(values.newEvents)
            }
        },
        fetchOrPollFailure: ({ error }: { error: ApiError }) => {
            errorToast(
                undefined,
                'There was a problem fetching your events. Please refresh this page to try again.',
                error.statusText,
                error.status
            )
        },
        toggleAutomaticLoad: ({ automaticLoadEnabled }) => {
            if (automaticLoadEnabled) {
                actions.prependNewEvents()
            }
        },
    }),
})
