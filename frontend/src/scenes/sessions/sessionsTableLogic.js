import { kea } from 'kea'
import api from 'lib/api'
import moment from 'moment'
import { toParams } from 'lib/utils'

export const sessionsTableLogic = kea({
    loaders: ({ actions }) => ({
        sessions: {
            __default: [],
            loadSessions: async (selectedDate) => {
                const response = await api.get(
                    'api/event/sessions' + (selectedDate ? '/?date_from=' + selectedDate.toISOString() : '')
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
    listeners: ({ values, actions }) => ({
        fetchNextSessions: async () => {
            const response = await api.get(
                'api/event/sessions/?' +
                    toParams({ date_from: values.selectedDate.toISOString(), offset: values.offset })
            )
            if (response.offset) actions.setOffset(response.offset)
            else actions.setOffset(null)
            actions.appendNewSessions(response.result)
        },
        dateChanged: ({ date }) => {
            actions.loadSessions(date)
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadSessions,
    }),
})
