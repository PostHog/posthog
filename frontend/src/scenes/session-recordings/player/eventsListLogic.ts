import { kea } from 'kea'
import { RecordingEventsFilters } from '~/types'
import { sessionRecordingLogic } from 'scenes/session-recordings/sessionRecordingLogic'
import { eventsListLogicType } from './eventsListLogicType'

export const eventsListLogic = kea<eventsListLogicType>({
    connect: {
        actions: [sessionRecordingLogic, ['setFilters']],
    },
    actions: {
        setLocalFilters: (filters: Partial<RecordingEventsFilters>) => ({ filters }),
    },
    reducers: {
        localFilters: [
            {} as Partial<RecordingEventsFilters>,
            {
                setLocalFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
    },
    listeners: ({ actions, values }) => ({
        setLocalFilters: async (_, breakpoint) => {
            await breakpoint(250)
            actions.setFilters(values.localFilters)
        },
    }),
})
