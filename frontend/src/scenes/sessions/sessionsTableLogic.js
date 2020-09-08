import { kea } from 'kea'
import api from 'lib/api'
import moment from 'moment'
import { toParams } from 'lib/utils'

export const sessionsTableLogic = kea({
    loaders: ({ actions, values }) => ({
        sessions: {
            __default: [],
            loadSessions: async (selectedDate) => {
                const response = await api.get(
                    'api/insight/session' + (selectedDate ? '/?date_from=' + values.selectedDateURLparam : '')
                )
                if (response.offset) actions.setOffset(response.offset)
                if (response.date_from) actions.setDate(moment(response.date_from).startOf('day'))
                return response.result
            },
        },
    }),
    actions: () => ({
        setOffset: (offset) => ({ offset }),
        fetchNextSessions: true,
        appendNewSessions: (sessions) => ({ sessions }),
        dateChanged: (date) => ({ date }),
        setDate: (date) => ({ date }),
    }),
    reducers: () => ({
        sessions: {
            appendNewSessions: (state, { sessions }) => [...state, ...sessions],
        },
        isLoadingNext: [false, { fetchNextSessions: () => true, appendNewSessions: () => false }],
        offset: [
            null,
            {
                setOffset: (_, { offset }) => offset,
            },
        ],
        selectedDate: [moment().startOf('day'), { dateChanged: (_, { date }) => date, setDate: (_, { date }) => date }],
    }),
    selectors: ({ selectors }) => ({
        selectedDateURLparam: [() => [selectors.selectedDate], (selectedDate) => selectedDate.toISOString()],
    }),
    listeners: ({ values, actions }) => ({
        fetchNextSessions: async () => {
            const response = await api.get(
                'api/insight/session/?' + toParams({ date_from: values.selectedDateURLparam, offset: values.offset })
            )
            if (response.offset) actions.setOffset(response.offset)
            else actions.setOffset(null)
            actions.appendNewSessions(response.result)
        },
        dateChanged: ({ date }) => {
            actions.loadSessions(date)
            actions.setOffset(null)
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadSessions,
    }),
})
