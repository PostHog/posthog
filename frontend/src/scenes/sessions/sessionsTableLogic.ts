import { kea } from 'kea'
import api from 'lib/api'
import moment from 'moment'
import { toParams } from 'lib/utils'
import { sessionsTableLogicType } from 'types/scenes/sessions/sessionsTableLogicType'
import { SessionType } from '~/types'

type Moment = moment.Moment

export const sessionsTableLogic = kea<sessionsTableLogicType<Moment, SessionType>>({
    loaders: ({ actions, values }) => ({
        sessions: {
            __default: [] as SessionType[],
            loadSessions: async (_: any, breakpoint) => {
                const { selectedDateURLparam } = values
                const params = toParams({
                    date_from: selectedDateURLparam,
                    date_to: selectedDateURLparam,
                    offset: 0,
                })
                const response = await api.get(`api/insight/session/?${params}`)
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
        dateChanged: (date: Moment | null) => ({ date }),
        previousDay: true,
        nextDay: true,
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
        selectedDate: [null as null | Moment, { dateChanged: (_, { date }) => date }],
    },
    selectors: {
        selectedDateURLparam: [(s) => [s.selectedDate], (selectedDate) => selectedDate?.format('YYYY-MM-DD')],
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
        dateChanged: () => {
            actions.loadSessions(true)
            actions.setNextOffset(null)
        },
        previousDay: () => {
            actions.dateChanged(moment(values.selectedDate).add(-1, 'day'))
        },
        nextDay: () => {
            actions.dateChanged(moment(values.selectedDate).add(1, 'day'))
        },
    }),
    actionToUrl: ({ values }) => ({
        dateChanged: () => {
            const { selectedDateURLparam } = values
            const today = moment().startOf('day').format('YYYY-MM-DD')
            return [`/sessions`, selectedDateURLparam === today ? {} : { date: selectedDateURLparam }]
        },
    }),
    urlToAction: ({ actions, values }) => ({
        '/sessions': (_: any, { date }: { date: string }) => {
            const newDate = date ? moment(date).startOf('day') : moment().startOf('day')
            if (!values.selectedDate || values.selectedDate.format('YYYY-MM-DD') !== newDate.format('YYYY-MM-DD')) {
                actions.dateChanged(newDate)
            }
        },
    }),
})
