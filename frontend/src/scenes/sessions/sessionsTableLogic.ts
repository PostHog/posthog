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

interface Params {
    date?: string
    properties?: any
    duration?: any
    sessionRecordingId?: SessionRecordingId
}

export type RecordingDurationFilter = ['lt' | 'gt', number | null, 's' | 'm' | 'h']

const buildURL = (
    selectedDateURLparam?: string,
    sessionRecordingId?: SessionRecordingId | null,
    duration?: RecordingDurationFilter | null
): [string, Params] => {
    const today = moment().startOf('day').format('YYYY-MM-DD')
    const params: Params = {}

    const { properties } = router.values.searchParams // eslint-disable-line
    if (selectedDateURLparam !== today) {
        params.date = selectedDateURLparam
    }
    if (properties) {
        params.properties = properties
    }
    if (duration) {
        params.duration = duration
    }
    if (sessionRecordingId) {
        params.sessionRecordingId = sessionRecordingId
    }

    return [router.values.location.pathname, params]
}

export const sessionsTableLogic = kea<
    sessionsTableLogicType<
        Moment,
        SessionType,
        SessionRecordingId,
        eventWithTime,
        PropertyFilter,
        RecordingDurationFilter
    >
>({
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
                    ...values.durationFilter,
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
        setFilters: (
            properties: Array<PropertyFilter>,
            selectedDate: Moment | null,
            duration: RecordingDurationFilter | null
        ) => ({ properties, selectedDate, duration }),
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
        duration: [
            null as RecordingDurationFilter | null,
            {
                setFilters: (_, { duration }) => duration,
            },
        ],
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
        durationFilter: [
            (selectors) => [selectors.duration],
            (duration: RecordingDurationFilter | null) => {
                if (!duration) {
                    return undefined
                }

                const multipliers = { s: 1, m: 60, h: 3600 }
                const seconds = (duration[1] || 0) * multipliers[duration[2]]
                return { duration_operator: duration[0], duration: seconds }
            },
        ],
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
                ...values.durationFilter,
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
        setFilters: () => {
            actions.setNextOffset(null)
            actions.loadSessions(true)
        },
        previousDay: () => {
            actions.setFilters(values.properties, moment(values.selectedDate).add(-1, 'day'), values.duration)
        },
        nextDay: () => {
            actions.setFilters(values.properties, moment(values.selectedDate).add(1, 'day'), values.duration)
        },
    }),
    actionToUrl: ({ values }) => ({
        setFilters: () => buildURL(values.selectedDateURLparam, values.sessionRecordingId, values.duration),
        setSessionRecordingId: () => buildURL(values.selectedDateURLparam, values.sessionRecordingId, values.duration),
        closeSessionPlayer: () => buildURL(values.selectedDateURLparam, null, values.duration),
    }),
    urlToAction: ({ actions, values }) => ({
        '*': (_: any, params: Params) => {
            const newDate = params.date ? moment(params.date).startOf('day') : moment().startOf('day')

            if (
                JSON.stringify(params.properties || []) !== JSON.stringify(values.properties) ||
                JSON.stringify(params.duration || {}) !== JSON.stringify(values.duration || {}) ||
                !values.selectedDate ||
                (values.selectedDate && values.selectedDate.format('YYYY-MM-DD') !== newDate.format('YYYY-MM-DD'))
            ) {
                actions.setFilters(params.properties || [], newDate, params.duration || null)
            } else if (values.sessions.length === 0) {
                actions.loadSessions(true)
            }

            if (params.sessionRecordingId && params.sessionRecordingId !== values.sessionRecordingId) {
                actions.setSessionRecordingId(params.sessionRecordingId)
            }
        },
    }),
})
