import { actions, kea, path, reducers, selectors } from 'kea'
import { getFunnelDatasetKey, getTrendDatasetKey } from 'scenes/insights/utils'

import { isFunnelsQuery, isInsightVizNode, isTrendsQuery } from '~/queries/utils'
import { DashboardTile, FunnelVizType, QueryBasedInsightModel } from '~/types'

import { BreakdownColorConfig } from './DashboardInsightColorsModal'
import type { dashboardInsightColorsModalLogicType } from './dashboardInsightColorsModalLogicType'
import { dashboardLogic } from './dashboardLogic'

type BreakdownValueAndType = Omit<BreakdownColorConfig, 'colorToken'>

export function extractBreakdownValues(
    insightTiles: DashboardTile<QueryBasedInsightModel>[] | null
): BreakdownValueAndType[] {
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
                    const breakdownType = querySource.breakdownFilter?.breakdown_type || 'event'
                    const breakdownValues: BreakdownValueAndType[] = [
                        {
                            breakdownValue: 'Baseline',
                            breakdownType,
                        },
                    ]
                    tile.insight?.result.forEach((result: any) => {
                        const key = getFunnelDatasetKey(result)
                        const keyParts = JSON.parse(key)
                        const breakdownValue = keyParts['breakdown_value']
                        breakdownValues.push({
                            breakdownValue: Array.isArray(breakdownValue) ? breakdownValue.join('::') : breakdownValue,
                            breakdownType,
                        })
                    })
                    return breakdownValues
                } else if (isTrendsQuery(querySource)) {
                    const breakdownType = querySource.breakdownFilter?.breakdown_type || 'event'
                    return tile.insight?.result.map((result: any) => {
                        const key = getTrendDatasetKey(result)
                        const keyParts = JSON.parse(key)
                        const breakdownValue = keyParts['breakdown_value']
                        return {
                            breakdownValue: Array.isArray(breakdownValue) ? breakdownValue.join('::') : breakdownValue,
                            breakdownType,
                        }
                    })
                }
                return []
            }
            return []
        })
        .filter((value) => value != null)
        .reduce<BreakdownValueAndType[]>((acc, curr) => {
            if (!acc.some((x) => x.breakdownValue === curr.breakdownValue && x.breakdownType === curr.breakdownType)) {
                acc.push(curr)
            }
            return acc
        }, [])
        .sort((a, b) => a.breakdownValue.localeCompare(b.breakdownValue))
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
