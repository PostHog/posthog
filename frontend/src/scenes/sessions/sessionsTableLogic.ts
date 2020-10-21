import { kea } from 'kea'
import api from 'lib/api'
import moment from 'moment'
import { toParams } from 'lib/utils'
import { sessionsTableLogicType } from 'types/scenes/sessions/sessionsTableLogicType'
import { PropertyFilter, SessionType } from '~/types'
import { router } from 'kea-router'
import { eventWithTime } from 'rrweb/typings/types'

type Moment = moment.Moment

type SessionRecordingId = string

type Params = {
    date?: string
    properties?: any
    sessionRecordingId?: SessionRecordingId,
}

const buildURL = (selectedDateURLparam: string, sessionRecordingId: SessionRecordingId | null): [string, Params] => {
    const today = moment().startOf('day').format('YYYY-MM-DD')
    const params: Params = {}

    const { properties } = router.values.searchParams // eslint-disable-line
    if (selectedDateURLparam !== today) {
        params.date = selectedDateURLparam
    }
    if (properties) {
        params.properties = properties
    }
    if (sessionRecordingId) {
        params.sessionRecordingId = sessionRecordingId
    }

    return [router.values.location.pathname, params]
}

export const sessionsTableLogic = kea<sessionsTableLogicType<Moment, SessionType>>({
    props: {} as {
        personIds?: string[]
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
                    properties: values.properties,
                })
                await breakpoint(10)
                const response = await api.get(`api/insight/session/?${params}`)
                breakpoint()
                if (response.offset) {
                    actions.setNextOffset(response.offset)
                }
                return response.result
            },
        },
        sessionPlayerData: {
            loadSessionPlayer: async (sessionRecordingId: SessionRecordingId): Promise<eventWithTime[]> => {
                const params = toParams({ session_recording_id: sessionRecordingId })
                const response = await api.get(`api/event/session_recording?${params}`)
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
        setFilters: (properties: Array<PropertyFilter>, selectedDate: Moment | null) => ({ properties, selectedDate }),
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
            [],
            {
                setFilters: (_, { properties }) => properties,
            },
        ],
        sessionRecordingId: [
            null as SessionRecordingId | null,
            {
                loadSessionPlayer: (_, params: SessionRecordingId) => params,
                closeSessionPlayer: () => null,
            },
        ],
        sessionPlayerData: [
            null as null | eventWithTime[],
            {
                closeSessionPlayer: () => null,
            },
        ],
    },
    selectors: {
        selectedDateURLparam: [(s) => [s.selectedDate], (selectedDate) => selectedDate?.format('YYYY-MM-DD')],
        sessionRecordingIds: [
            (selectors) => [selectors.sessions],
            (sessions: Array<SessionType>): string[] =>
                sessions.flatMap((session) => session.session_recording_ids)
        ],
        playerSessionIndex: [
            (selectors) => [selectors.sessions, selectors.sessionPlayerParams],
            (sessions: SessionType[], params: RecordingParams | null) => {
                if (!params) {
                    return null
                }
                const index
                params && sessions.findIndex((session) => session.session_recording_ids.includes(params.sessionRecordingId))
            }
        ],
    },
    listeners: ({ values, actions }) => ({
        fetchNextSessions: async (_, breakpoint) => {
            const params = toParams({
                date_from: values.selectedDateURLparam,
                date_to: values.selectedDateURLparam,
                offset: values.nextOffset,
            })
            const response = await api.get(`api/insight/session/?${params}`)
            breakpoint()
            if (response.offset) {
                actions.setNextOffset(response.offset)
            } else {
                actions.setNextOffset(null)
            }
            actions.appendNewSessions(response.result)
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
    actionToUrl: ({ values }) => ({
        setFilters: () => buildURL(values.selectedDateURLparam, values.sessionRecordingId),
        loadSessionPlayer: () => buildURL(values.selectedDateURLparam, values.sessionRecordingId),
        closeSessionPlayer: () => buildURL(values.selectedDateURLparam, values.sessionRecordingId),
    }),
    urlToAction: ({ actions, values }) => ({
        '/sessions': (_: any, params: Params) => {
            const newDate = params.date ? moment(params.date).startOf('day') : moment().startOf('day')
            actions.setFilters(params.properties || [], newDate)

            if (params.sessionRecordingId) {
                actions.loadSessionPlayer(params.sessionRecordingId)
            }
        },
        '/person/*': (_: any, params: Params) => {
            const newDate = params.date ? moment(params.date).startOf('day') : moment().startOf('day')
            if (!values.selectedDate || values.selectedDate.format('YYYY-MM-DD') !== newDate.format('YYYY-MM-DD')) {
                actions.setFilters(params.properties || [], newDate)
            }

            if (params.sessionRecordingId) {
                actions.loadSessionPlayer(params.sessionRecordingId)
            }
        },
    }),
})
