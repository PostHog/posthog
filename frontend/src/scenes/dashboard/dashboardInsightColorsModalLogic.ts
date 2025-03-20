import { actions, kea, path, reducers } from 'kea'

import type { dashboardInsightColorsModalLogicType } from './dashboardInsightColorsModalLogicType'

export const dashboardInsightColorsModalLogic = kea<dashboardInsightColorsModalLogicType>([
    path(['scenes', 'dashboard', 'dashboardInsightColorsModalLogic']),
    actions(() => ({
        showInsightColorsModal: true,
        hideInsightColorsModal: true,
    })),
    reducers({
        isOpen: [
            false,
            {
                showInsightColorsModal: () => true,
                hideInsightColorsModal: () => false,
            },
        ],
    }),
])
