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
            loadSessions: async () => {
                const { selectedDateURLparam } = values
                const params = toParams({
                    date_from: selectedDateURLparam,
                    date_to: selectedDateURLparam,
                    offset: values.offset,
                })
                const response = await api.get(`api/insight/session/?${params}`)
                if (response.offset) {
                    actions.setOffset(response.offset)
                }
                return response.result
            },
        },
    }),
    actions: () => ({
        setOffset: (offset: number | null) => ({ offset }),
        fetchNextSessions: true,
        appendNewSessions: (sessions) => ({ sessions }),
        dateChanged: (date: Moment | null) => ({ date }),
    }),
    reducers: {
        sessions: {
            appendNewSessions: (state, { sessions }) => [...state, ...sessions],
        },
        isLoadingNext: [false, { fetchNextSessions: () => true, appendNewSessions: () => false }],
        offset: [
            null as null | number,
            {
                setOffset: (_, { offset }) => offset,
            },
        ],
        selectedDate: [moment().startOf('day') as null | Moment, { dateChanged: (_, { date }) => date }],
    },
    selectors: {
        selectedDateURLparam: [(s) => [s.selectedDate], (selectedDate) => selectedDate?.format('YYYY-MM-DD')],
    },
    listeners: ({ values, actions }) => ({
        fetchNextSessions: async () => {
            const params = toParams({
                date_from: values.selectedDateURLparam,
                date_to: values.selectedDateURLparam,
                offset: values.offset,
            })
            const response = await api.get(`api/insight/session/?${params}`)
            if (response.offset) {
                actions.setOffset(response.offset)
            } else {
                actions.setOffset(null)
            }
            actions.appendNewSessions(response.result)
        },
        dateChanged: () => {
            actions.loadSessions()
            actions.setOffset(null)
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadSessions()
        },
    }),
    actionToUrl: ({ values }) => ({
        dateChanged: () => {
            const { selectedDateURLparam } = values
            const today = moment().startOf('day').format('YYYY-MM-DD')
            return [`/sessions`, selectedDateURLparam === today ? {} : { date: selectedDateURLparam }]
        },
    }),
    urlToAction: ({ actions }) => ({
        '/sessions': (_: any, { date }: { date: string }) =>
            actions.dateChanged(date ? moment(date).startOf('day') : moment().startOf('day')),
    }),
})
