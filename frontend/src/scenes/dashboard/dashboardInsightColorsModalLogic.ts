import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { cohortsModel } from '~/models/cohortsModel'
import { DashboardTile, QueryBasedInsightModel } from '~/types'

import { BreakdownValueAndType, extractBreakdownValues } from './dashboardBreakdownColors'
import type { dashboardInsightColorsModalLogicType } from './dashboardInsightColorsModalLogicType'
import { dashboardLogic } from './dashboardLogic'

// Re-export for back-compat with existing imports/tests.
export { extractBreakdownValues }
export type { BreakdownValueAndType }

export const dashboardInsightColorsModalLogic = kea<dashboardInsightColorsModalLogicType>([
    path(['scenes', 'dashboard', 'dashboardInsightColorsModalLogic']),
    connect(() => ({
        values: [cohortsModel, ['allCohorts']],
    })),
    actions({
        showInsightColorsModal: (id: number) => ({ id }),
        hideInsightColorsModal: true,
    }),
    reducers({
        dashboardId: [
            null as number | null,
            {
                showInsightColorsModal: (_, { id }) => id,
                hideInsightColorsModal: () => null,
            },
        ],
    }),
    selectors({
        isOpen: [(s) => [s.dashboardId], (dashboardId) => dashboardId != null],
        insightTiles: [
            (s) => [(state) => dashboardLogic.findMounted({ id: s.dashboardId(state) })?.values.insightTiles || null],
            (insightTiles): DashboardTile<QueryBasedInsightModel>[] | null => insightTiles,
        ],
        insightTilesLoading: [
            (s) => [(state) => dashboardLogic.findMounted({ id: s.dashboardId(state) })?.values.itemsLoading || null],
            (itemsLoading): boolean | null => itemsLoading,
            { resultEqualityCheck: () => false },
        ],
        breakdownValues: [
            (s) => [s.insightTiles, s.allCohorts],
            (insightTiles, allCohorts) => extractBreakdownValues(insightTiles, allCohorts?.results),
        ],
    }),
])
