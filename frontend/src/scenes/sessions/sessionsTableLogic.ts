import { kea } from 'kea'
import api from 'lib/api'
import dayjs from 'dayjs'
import equal from 'fast-deep-equal'
import { toParams } from 'lib/utils'
import { sessionsTableLogicType } from './sessionsTableLogicType'
import { EventType, PropertyFilter, SessionsPropertyFilter, SessionType } from '~/types'
import { router } from 'kea-router'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'

type SessionRecordingId = string

type Dayjs = dayjs.Dayjs

interface Params {
    date?: string
    properties?: any
    sessionRecordingId?: SessionRecordingId
    filters?: Array<SessionsPropertyFilter>
}

export const sessionsTableLogic = kea<
    sessionsTableLogicType<Dayjs, SessionType, SessionRecordingId, PropertyFilter, SessionsPropertyFilter, EventType>
>({
    key: (props) => props.personIds || 'global',
    props: {} as {
        personIds?: string[]
    },
    connect: {
        values: [sessionsFiltersLogic, ['filters']],
        actions: [sessionsFiltersLogic, ['setAllFilters']],
    },
    loaders: ({ actions, values, props }) => ({
        sessions: {
            __default: [] as SessionType[],
            loadSessions: async (_: any, breakpoint) => {
                const { selectedDateURLparam } = values
                const params = toParams({
                    date_from: selectedDateURLparam,
                    date_to: selectedDateURLparam,
                    offset: 0,
                    distinct_id: props.personIds ? props.personIds[0] : '',
                    filters: values.filters,
                    properties: values.properties,
                })
                await breakpoint(10)
                const response = await api.get(`api/event/sessions/?${params}`)
                breakpoint()
                actions.setPagination(response.pagination)
                return response.result
            },
        },
    }),
    actions: () => ({
        setPagination: (pagination: Record<string, any> | null) => ({ pagination }),
        fetchNextSessions: true,
        appendNewSessions: (sessions) => ({ sessions }),
        previousDay: true,
        nextDay: true,
        applyFilters: true,
        setFilters: (properties: Array<PropertyFilter>, selectedDate: Dayjs | null) => ({
            properties,
            selectedDate,
        }),
        setSessionRecordingId: (sessionRecordingId: SessionRecordingId) => ({ sessionRecordingId }),
        closeSessionPlayer: true,
        loadSessionEvents: (session: SessionType) => ({ session }),
        addSessionEvents: (session: SessionType, events: EventType[]) => ({ session, events }),
        setLastAppliedFilters: (filters: SessionsPropertyFilter[]) => ({ filters }),
    }),
    reducers: {
        sessions: {
            appendNewSessions: (state, { sessions }) => [...state, ...sessions],
            loadSessionsFailure: () => [],
        },
        isLoadingNext: [false, { fetchNextSessions: () => true, appendNewSessions: () => false }],
        pagination: [
            null as Record<string, any> | null,
            {
                setPagination: (_, { pagination }) => pagination,
                loadSessionsFailure: () => null,
            },
        ],
        selectedDate: [null as null | dayjs.Dayjs, { setFilters: (_, { selectedDate }) => selectedDate }],
        properties: [
            [] as PropertyFilter[],
            {
                setFilters: (_, { properties }) => properties,
            },
        ],
        sessionRecordingId: [
            null as SessionRecordingId | null,
            {
                setSessionRecordingId: (_, { sessionRecordingId }) => sessionRecordingId,
                closeSessionPlayer: () => null,
            },
        ],
        loadedSessionEvents: [
            {} as Record<string, EventType[] | undefined>,
            {
                addSessionEvents: (state, { session, events }) => ({
                    ...state,
                    [session.global_session_id]: events,
                }),
            },
        ],
        lastAppliedFilters: [
            [] as SessionsPropertyFilter[],
            {
                setLastAppliedFilters: (_, { filters }) => filters,
            },
        ],
    },
    selectors: {
        selectedDateURLparam: [(s) => [s.selectedDate], (selectedDate) => selectedDate?.format('YYYY-MM-DD')],
        orderedSessionRecordingIds: [
            (selectors) => [selectors.sessions],
            (sessions: SessionType[]): SessionRecordingId[] =>
                Array.from(new Set(sessions.flatMap((session) => session.session_recordings.map(({ id }) => id)))),
        ],
        firstRecordingId: [
            (selectors) => [selectors.orderedSessionRecordingIds],
            (ids: SessionRecordingId[]): SessionRecordingId | null => ids[0] || null,
        ],
        filtersDirty: [
            (selectors) => [selectors.filters, selectors.lastAppliedFilters],
            (filters, lastFilters): boolean => !equal(filters, lastFilters),
        ],
    },
    listeners: ({ values, actions, props }) => ({
        fetchNextSessions: async (_, breakpoint) => {
            const params = toParams({
                date_from: values.selectedDateURLparam,
                date_to: values.selectedDateURLparam,
                pagination: values.pagination,
                distinct_id: props.personIds ? props.personIds[0] : '',
                filters: values.filters,
                properties: values.properties,
            })
            const response = await api.get(`api/event/sessions/?${params}`)
            breakpoint()
            actions.setPagination(response.pagination)
            actions.appendNewSessions(response.result)
        },
        applyFilters: () => {
            actions.setPagination(null)
            actions.loadSessions(true)
            actions.setLastAppliedFilters(values.filters)
        },
        setFilters: () => {
            actions.setPagination(null)
            actions.loadSessions(true)
        },
        previousDay: () => {
            actions.setFilters(values.properties, dayjs(values.selectedDate).add(-1, 'day'))
        },
        nextDay: () => {
            actions.setFilters(values.properties, dayjs(values.selectedDate).add(1, 'day'))
        },
        loadSessionEvents: async ({ session }, breakpoint) => {
            if (!values.loadedSessionEvents[session.global_session_id]) {
                const params = {
                    distinct_id: session.distinct_id,
                    date_from: session.start_time,
                    date_to: session.end_time,
                }

                await breakpoint(200)

                const response = await api.get(`api/event/session_events?${toParams(params)}`)
                actions.addSessionEvents(session, response.result)
            }
        },
    }),
    actionToUrl: ({ values }) => {
        const buildURL = (overrides: Partial<Params> = {}): [string, Params] => {
            const today = dayjs().startOf('day').format('YYYY-MM-DD')

            const { properties } = router.values.searchParams // eslint-disable-line

            const params: Params = {
                date: values.selectedDateURLparam !== today ? values.selectedDateURLparam : undefined,
                properties: properties || undefined,
                sessionRecordingId: values.sessionRecordingId || undefined,
                filters: values.filters,
                ...overrides,
            }

            return [router.values.location.pathname, params]
        }

        return {
            setFilters: () => buildURL(),
            loadSessions: () => buildURL(),
            setSessionRecordingId: () => buildURL(),
            closeSessionPlayer: () => buildURL({ sessionRecordingId: undefined }),
        }
    },
    urlToAction: ({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            const newDate = params.date ? dayjs(params.date).startOf('day') : dayjs().startOf('day')

            if (
                JSON.stringify(params.properties || []) !== JSON.stringify(values.properties) ||
                !values.selectedDate ||
                values.selectedDate.format('YYYY-MM-DD') !== newDate.format('YYYY-MM-DD')
            ) {
                actions.setFilters(params.properties || [], newDate)
            } else if (values.sessions.length === 0 && !values.sessionsLoading) {
                actions.loadSessions(true)
            }

            if (params.sessionRecordingId && params.sessionRecordingId !== values.sessionRecordingId) {
                actions.setSessionRecordingId(params.sessionRecordingId)
            }

            if (JSON.stringify(params.filters || {}) !== JSON.stringify(values.filters)) {
                actions.setAllFilters(params.filters || [])
                actions.applyFilters()
            }
        }

        return {
            '/sessions': urlToAction,
            '/person/*': urlToAction,
        }
    },
})
