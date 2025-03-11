import { actions, kea, path, reducers, selectors } from 'kea'

import type { dashboardInsightColorsLogicType } from './dashboardInsightColorsLogicType'

export const dashboardInsightColorsLogic = kea<dashboardInsightColorsLogicType>([
    path(['scenes', 'dashboard', 'dashboardInsightColorsLogic']),
    actions({
        showDashboardInsightColorsModal: (id: number) => ({ id }),
        hideDashboardInsightColorsModal: true,
    }),
    reducers({
        dashboardId: [
            null as number | null,
            {
                showDashboardInsightColorsModal: (_, { id }) => id,
                hideDashboardInsightColorsModal: () => null,
            },
        ],
    }),
    selectors({
        dashboardInsightColorsModalVisible: [(s) => [s.dashboardId], (dashboardId) => dashboardId != null],
    }),
])
