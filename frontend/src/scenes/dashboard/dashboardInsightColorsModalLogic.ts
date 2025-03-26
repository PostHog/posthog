import { actions, kea, path, reducers, selectors } from 'kea'
import { getFunnelDatasetKey, getTrendDatasetKey } from 'scenes/insights/utils'

import { isFunnelsQuery, isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { DashboardTile, FunnelVizType, QueryBasedInsightModel } from '~/types'

import type { dashboardInsightColorsModalLogicType } from './dashboardInsightColorsModalLogicType'
import { dashboardLogic } from './dashboardLogic'

function extractBreakdownValues(insightTiles: DashboardTile<QueryBasedInsightModel>[] | null): string[] {
    if (insightTiles == null) {
        return []
    }

    return insightTiles
        .flatMap((tile) => {
            if (isInsightVizNode(tile.insight?.query)) {
                const querySource = tile.insight?.query.source
                if (
                    isFunnelsQuery(querySource) &&
                    (querySource.funnelsFilter?.funnelVizType === undefined ||
                        querySource.funnelsFilter?.funnelVizType === FunnelVizType.Steps)
                ) {
                    const breakdownValues = ['Baseline']
                    tile.insight?.result.forEach((result: any) => {
                        const key = getFunnelDatasetKey(result)
                        const keyParts = JSON.parse(key)
                        breakdownValues.push(keyParts['breakdown_value'])
                    })
                    return breakdownValues
                } else if (isTrendsQuery(querySource)) {
                    return tile.insight?.result.map((result: any) => {
                        const key = getTrendDatasetKey(result)
                        const keyParts = JSON.parse(key)
                        return keyParts['breakdown_value']
                    })
                }
                return []
            }
            return []
        })
        .filter((value) => value != null)
        .sort()
}

export const dashboardInsightColorsModalLogic = kea<dashboardInsightColorsModalLogicType>([
    path(['scenes', 'dashboard', 'dashboardInsightColorsModalLogic']),
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
            { resultEqualityCheck: () => false, equalityCheck: () => false },
        ],
        breakdownValues: [(s) => [s.insightTiles], (insightTiles) => extractBreakdownValues(insightTiles)],
    }),
])
