import { kea } from 'kea'
import api from 'lib/api'
import { activityHistoryLogicType } from './activityHistoryLogicType'

export const activityHistoryLogic = kea<activityHistoryLogicType>({
    actions: () => ({
        setShowActivityHistory: (show: boolean) => ({ show }),
    }),

    reducers: () => ({
        showActivityHistory: [
            false,
            {
                setShowActivityHistory: (_, { show }) => show,
            },
        ],
        id: [
            null,
            {
                setActivityHistoryId: (_, { id }) => id,
            },
        ],
    }),

    loaders: () => ({
        activityHistory: {
            loadActivityHistory: async (id) => {
                const response = await api.get(`api/activity_history/?parent=${id}`)
                return response.results
            },
        },
    }),
})
