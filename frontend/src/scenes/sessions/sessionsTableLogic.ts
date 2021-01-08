import { kea } from 'kea'
import api from 'lib/api'
import moment from 'moment'
import { toParams } from 'lib/utils'
import { sessionsTableLogicType } from 'types/scenes/sessions/sessionsTableLogicType'
import { PropertyFilter, SessionsPropertyFilter, SessionType } from '~/types'
import { router } from 'kea-router'
import { sessionsFiltersLogic } from 'scenes/sessions/filters/sessionsFiltersLogic'

type Moment = moment.Moment

type SessionRecordingId = string

interface Params {
    date?: string
    properties?: any
    sessionRecordingId?: SessionRecordingId
    filters?: Array<SessionsPropertyFilter>
}

export const sessionsTableLogic = kea<
    sessionsTableLogicType<Moment, SessionType, SessionRecordingId, PropertyFilter, SessionsPropertyFilter>
>({
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
                if (response.offset) {
                    actions.setNextOffset(response.offset)
                }
                return response.result
            },
        },
    }),
    actions: () => ({
        setNextOffset: (nextOffset: number | null) => ({ nextOffset }),
        fetchNextSessions: true,
        appendNewSessions: (sessions) => ({ sessions }),
        previousDay: true,
        nextDay: true,
        applyFilters: true,
        setFilters: (properties: Array<PropertyFilter>, selectedDate: Moment | null) => ({ properties, selectedDate }),
        setSessionRecordingId: (sessionRecordingId: SessionRecordingId) => ({ sessionRecordingId }),
        closeSessionPlayer: true,
    }),
    reducers: {
        sessions: {
            appendNewSessions: (state, { sessions }) => [...state, ...sessions],
            loadSessionsFailure: () => [],
        },
        isLoadingNext: [false, { fetchNextSessions: () => true, appendNewSessions: () => false }],
        nextOffset: [
            null as null | number,
            {
                setNextOffset: (_, { nextOffset }) => nextOffset,
                loadSessionsFailure: () => null,
            },
        ],
        selectedDate: [null as null | Moment, { setFilters: (_, { selectedDate }) => selectedDate }],
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
    },
    selectors: {
        selectedDateURLparam: [(s) => [s.selectedDate], (selectedDate) => selectedDate?.format('YYYY-MM-DD')],
        orderedSessionRecordingIds: [
            (selectors) => [selectors.sessions],
            (sessions: SessionType[]): SessionRecordingId[] =>
                Array.from(new Set(sessions.flatMap((session) => session.session_recording_ids))),
        ],
        firstRecordingId: [
            (selectors) => [selectors.orderedSessionRecordingIds],
            (ids: SessionRecordingId[]): SessionRecordingId | null => ids[0] || null,
        ],
    },
    listeners: ({ values, actions, props }) => ({
        fetchNextSessions: async (_, breakpoint) => {
            const params = toParams({
                date_from: values.selectedDateURLparam,
                date_to: values.selectedDateURLparam,
                offset: values.nextOffset,
                distinct_id: props.personIds ? props.personIds[0] : '',
                properties: values.properties,
            })
            const response = await api.get(`api/event/sessions/?${params}`)
            breakpoint()
            if (response.offset) {
                actions.setNextOffset(response.offset)
            } else {
                actions.setNextOffset(null)
            }
            actions.appendNewSessions(response.result)
        },
        applyFilters: () => {
            actions.setNextOffset(null)
            actions.loadSessions(true)
        },
        setFilters: () => {
            actions.setNextOffset(null)
            actions.loadSessions(true)
        },
        previousDay: () => {
            actions.setFilters(values.properties, moment(values.selectedDate).add(-1, 'day'))
        },
        nextDay: () => {
            actions.setFilters(values.properties, moment(values.selectedDate).add(1, 'day'))
        },
    }),
    actionToUrl: ({ values }) => {
        const buildURL = (overrides: Partial<Params> = {}): [string, Params] => {
            const today = moment().startOf('day').format('YYYY-MM-DD')

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
    urlToAction: ({ actions, values }) => ({
        '*': (_: any, params: Params) => {
            const newDate = params.date ? moment(params.date).startOf('day') : moment().startOf('day')

            if (
                JSON.stringify(params.properties || []) !== JSON.stringify(values.properties) ||
                !values.selectedDate ||
                values.selectedDate.format('YYYY-MM-DD') !== newDate.format('YYYY-MM-DD')
            ) {
                actions.setFilters(params.properties || [], newDate)
            } else if (values.sessions.length === 0) {
                actions.loadSessions(true)
            }

            if (params.sessionRecordingId && params.sessionRecordingId !== values.sessionRecordingId) {
                actions.setSessionRecordingId(params.sessionRecordingId)
            }

            if (JSON.stringify(params.filters || {}) !== JSON.stringify(values.filters)) {
                actions.setAllFilters(params.filters || [])
                actions.applyFilters()
            }
        },
    }),
})
