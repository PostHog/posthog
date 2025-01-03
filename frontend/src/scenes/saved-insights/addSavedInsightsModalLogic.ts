import { kea } from 'kea'

import type { addSavedInsightsModalLogicType } from './addSavedInsightsModalLogicType'
import { savedInsightsLogic } from './savedInsightsLogic'

// This logic is used to control the pagination of the insights in the add saved insights to dashboard modal
export const addSavedInsightsModalLogic = kea<addSavedInsightsModalLogicType>({
    path: ['scenes', 'saved-insights', 'addSavedInsightsModalLogic'],
    connect: {
        logic: [savedInsightsLogic],
    },
    actions: () => ({
        setModalPage: (page: number) => ({ page }),
    }),

    reducers: () => ({
        modalPage: [
            1,
            {
                setModalPage: (_, { page }) => page,
            },
        ],
    }),

    listeners: () => ({
        setModalPage: async ({ page }) => {
            savedInsightsLogic.actions.setSavedInsightsFilters({ page }, true, false)
        },
    }),
})
