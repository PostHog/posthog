import { kea } from 'kea'
import { convertPropertyGroupToProperties, toParams } from 'lib/utils'
import { router } from 'kea-router'
import api from 'lib/api'
import type { eventsTableLogicType } from './eventsTableLogicType'
import { FixedFilters } from 'scenes/events/EventsTable'
import { AnyPropertyFilter, EventsTableRowItem, EventType, PropertyFilter, PropertyGroupFilter } from '~/types'
import { teamLogic } from '../teamLogic'
import { dayjs, now } from 'lib/dayjs'
import { lemonToast } from 'lib/components/lemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ExporterFormat, exporterLogic } from 'lib/components/ExportButton/exporterLogic'
import { FEATURE_FLAGS } from 'lib/constants'

const DAYS_FIRST_FETCH = 5
const DAYS_SECOND_FETCH = 365

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

const daysAgo = (days: number): string => now().subtract(days, 'day').toISOString()

export interface EventsTableLogicProps {
    fixedFilters?: FixedFilters
    key: string
    sceneUrl: string
    fetchMonths?: number
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

export const eventsTableLogic = kea<eventsTableLogicType>({
    path: (key) => ['scenes', 'events', 'eventsTableLogic', key],
    props: {} as EventsTableLogicProps,
    // Set a unique key based on the fixed filters.
    // This way if we move back/forward between /events and /person/ID, the logic is reloaded.
    key: (props) =>
        [props.fixedFilters ? JSON.stringify(props.fixedFilters) : 'all', props.key, props.sceneUrl]
            .filter((keyPart) => !!keyPart)
            .join('-'),
    connect: {
        values: [teamLogic, ['currentTeamId'], featureFlagLogic, ['featureFlags']],
        actions: [exporterLogic, ['exportItem']],
    },
    actions: {
        setPollingActive: (pollingActive: boolean) => ({
            pollingActive,
        }),
        setProperties: (
            properties: AnyPropertyFilter[] | AnyPropertyFilter | PropertyGroupFilter
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
        fetchEvents: (
            nextParams: {
                before: string
            } | null = null
        ) => ({ nextParams }),
        fetchEventsSuccess: (apiResponse: OnFetchEventsSuccess) => apiResponse,
        fetchNextEvents: true,
        fetchOrPollFailure: (error: ApiError) => ({ error }),
        pollEvents: true,
        pollEventsSuccess: (events: EventType[]) => ({ events }),
        prependEvents: (events: EventType[]) => ({ events }),
        prependNewEvents: true,
        setSelectedEvent: (selectedEvent: EventType) => ({ selectedEvent }),
        setPollTimeout: (pollTimeout: number) => ({ pollTimeout }),
        setEventFilter: (event: string) => ({ event }),
        toggleAutomaticLoad: (automaticLoadEnabled: boolean) => ({ automaticLoadEnabled }),
        noop: (s) => s,
        startDownload: true,
    },

    reducers: ({ props }) => ({
        pollingIsActive: [
            true,
            {
                setPollingActive: (_, { pollingActive }) => pollingActive,
                pollEventsSuccess: (state, { events }) => (events && events.length ? false : state),
                prependNewEvents: () => true,
                toggleAutomaticLoad: () => true,
            },
        ],
        properties: [
            [] as PropertyFilter[],
            {
                setProperties: (_, { properties }) => convertPropertyGroupToProperties(properties) as PropertyFilter[],
            },
        ],
        eventFilter: [
            props.fixedFilters?.event_filter ?? '',
            {
                setEventFilter: (_, { event }) => event,
            },
        ],
        isLoading: [
            true,
            {
                fetchEvents: () => true,
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
        orderBy: ['-timestamp', {}],
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
            { persist: true },
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
        exportParams: [
            () => [selectors.eventFilter, selectors.orderBy, selectors.properties, selectors.minimumExportDate],
            (eventFilter, orderBy, properties, minimumQueryDate) => ({
                ...(props.fixedFilters || {}),
                properties: [...properties, ...(props.fixedFilters?.properties || [])],
                ...(eventFilter ? { event: eventFilter } : {}),
                orderBy: [orderBy],
                after: minimumQueryDate,
            }),
        ],
        exportUrl: [
            () => [selectors.currentTeamId, selectors.exportParams],
            (teamId, exportParams) => `/api/projects/${teamId}/events.csv?${toParams(exportParams)}`,
        ],
        months: [() => [(_, prop) => prop.fetchMonths], (months) => months || 12],
        minimumExportDate: [() => [selectors.months], () => now().subtract(1, 'months').toISOString()],
        minimumQueryDate: [() => [selectors.months], (months) => now().subtract(months, 'months').toISOString()],
        pollAfter: [
            () => [selectors.events],
            (events) => (events?.length > 0 && events[0].timestamp ? events[0].timestamp : daysAgo(0)),
        ],
    }),

    actionToUrl: ({ values }) => ({
        setProperties: () => {
            return [
                router.values.location.pathname,
                {
                    ...router.values.searchParams,
                    properties: values.properties.length === 0 ? undefined : values.properties,
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
            if (!!values.featureFlags[FEATURE_FLAGS.ASYNC_EXPORT_CSV_FOR_LIVE_EVENTS]) {
                actions.exportItem(ExporterFormat.CSV, {}, values.exportParams)
            } else {
                lemonToast.success('The export is starting. It should finish soon')
                window.location.href = values.exportUrl
            }
        },
        setProperties: () => actions.fetchEvents(),
        setEventFilter: () => actions.fetchEvents(),
        fetchNextEvents: async () => {
            const { events } = values

            if (events.length === 0) {
                actions.fetchEvents()
            } else {
                actions.fetchEvents({
                    before: events[events.length - 1].timestamp,
                })
            }
        },
        fetchEvents: async ({ nextParams }, breakpoint) => {
            clearTimeout(values.pollTimeout)

            if (values.events.length > 0) {
                // 300ms debounce to prevent potentially over-eager filters from making too many requests
                await breakpoint(300)
            } else {
                // 1ms debounce to avoid parallel setProperties & setEventFilter calls
                // from making two consecutive requests
                await breakpoint(1)
            }

            const properties = [...values.properties, ...(props.fixedFilters?.properties || [])]

            async function getAPIResponse(after: string): Promise<any> {
                const params = {
                    after: after,
                    ...(props.fixedFilters || {}),
                    properties,
                    ...(nextParams || {}),
                    ...(values.eventFilter ? { event: values.eventFilter } : {}),
                    orderBy: [values.orderBy],
                }
                return api.get(`api/projects/${values.currentTeamId}/events/?${toParams(params)}`)
            }

            let apiResponse = null
            let usedSecondFetch = false

            try {
                apiResponse = await getAPIResponse(daysAgo(DAYS_FIRST_FETCH))

                if (apiResponse.results.length === 0) {
                    apiResponse = await getAPIResponse(daysAgo(DAYS_SECOND_FETCH))
                    usedSecondFetch = true
                }
            } catch (error) {
                actions.fetchOrPollFailure(error as ApiError)
                return
            }

            breakpoint()
            actions.fetchEventsSuccess({
                events: apiResponse.results,
                hasNext: !!apiResponse.next || !usedSecondFetch,
                // if we find less than limit events in first fetch, we shouldn't assume there are no more events
                // and instead allow re-fetching
                isNext: !!nextParams,
            })

            // uses window setTimeout because typegen had a hard time with NodeJS.Timeout
            const timeout = window.setTimeout(actions.pollEvents, POLL_TIMEOUT)
            actions.setPollTimeout(timeout)
        },
        pollEvents: async (_, breakpoint) => {
            function setNextPoll(): void {
                // uses window setTimeout because typegen had a hard time with NodeJS.Timeout
                const timeout = window.setTimeout(actions.pollEvents, POLL_TIMEOUT)
                actions.setPollTimeout(timeout)
            }

            // Poll events when they are ordered in ascending order based on timestamp
            if (values.orderBy !== '-timestamp') {
                return
            }

            // Do not poll if the scene is in the background
            if (props.sceneUrl !== router.values.location.pathname) {
                return
            }

            // if polling has been paused, check again after POLL_TIMEOUT milliseconds
            if (!values.pollingIsActive) {
                setNextPoll()
                return
            }

            const properties = [...values.properties, ...(props.fixedFilters?.properties || [])]

            const params: Record<string, unknown> = {
                ...(props.fixedFilters || {}),
                properties,
                ...(values.eventFilter ? { event: values.eventFilter } : {}),
                orderBy: [values.orderBy],
                after: values.pollAfter,
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

            setNextPoll()
        },
        prependNewEvents: () => {
            if (values.newEvents.length) {
                actions.prependEvents(values.newEvents)
            }
        },
        fetchOrPollFailure: ({ error }: { error: ApiError }) => {
            lemonToast.error(`There was a problem fetching your events: ${error.statusText}`)
        },
        toggleAutomaticLoad: ({ automaticLoadEnabled }) => {
            if (automaticLoadEnabled) {
                actions.prependNewEvents()
            }
        },
    }),
})
