import { actions, kea, path, reducers } from 'kea'

import type { dashboardInsightColorsLogicType } from './dashboardInsightColorsLogicType'

export const dashboardInsightColorsLogic = kea<dashboardInsightColorsLogicType>([
    path(['scenes', 'dashboard', 'dashboardInsightColorsLogic']),
    actions({
        showDashboardInsightColorsModal: (id: number) => ({ id }),
        hideDashboardInsightColorsModal: true,
    }),
    reducers({
        dashboardInsightColorsModalVisible: [
            false,
            {
                showDashboardInsightColorsModal: () => true,
                hideDashboardInsightColorsModal: () => false,
            },
        ],
    }),
])
