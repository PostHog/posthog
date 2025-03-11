import { actions, kea, path, reducers, selectors } from 'kea'

import { DashboardTile, QueryBasedInsightModel } from '~/types'

import type { dashboardInsightColorsLogicType } from './dashboardInsightColorsLogicType'
import { dashboardLogic } from './dashboardLogic'

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
        insightTiles: [
            (s) => [(state) => dashboardLogic.findMounted({ id: s.dashboardId(state) })?.values.insightTiles || null],
            (insightTiles): DashboardTile<QueryBasedInsightModel>[] | null => insightTiles,
        ],
    }),
])
