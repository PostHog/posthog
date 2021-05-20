import { kea } from 'kea'
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
    }),

})