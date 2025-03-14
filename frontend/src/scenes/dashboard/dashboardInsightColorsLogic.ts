import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { DataColorToken } from 'lib/colors'

import { DashboardTile, QueryBasedInsightModel } from '~/types'

import { dashboardColorsLogic } from './dashboardColorsLogic'
import type { dashboardInsightColorsLogicType } from './dashboardInsightColorsLogicType'
import { dashboardLogic } from './dashboardLogic'

export const dashboardInsightColorsLogic = kea<dashboardInsightColorsLogicType>([
    path(['scenes', 'dashboard', 'dashboardInsightColorsLogic']),
    actions({
        showDashboardInsightColorsModal: (id: number) => ({ id }),
        hideDashboardInsightColorsModal: true,
        setBreakdownColor: (breakdownValue: string, colorToken: DataColorToken) => ({ breakdownValue, colorToken }),
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
        insightTilesLoading: [
            (s) => [(state) => dashboardLogic.findMounted({ id: s.dashboardId(state) })?.values.itemsLoading || null],
            (itemsLoading): boolean | null => itemsLoading,
            { resultEqualityCheck: () => false, equalityCheck: () => false },
        ],
    }),
    listeners(({ values }) => ({
        setBreakdownColor: ({ breakdownValue, colorToken }) => {
            const builtDashboardColorsLogic = dashboardColorsLogic.findMounted({ id: values.dashboardId })
            builtDashboardColorsLogic?.actions.setBreakdownColor(breakdownValue, colorToken)
        },
    })),
])
