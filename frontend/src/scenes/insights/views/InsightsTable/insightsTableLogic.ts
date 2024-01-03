import { actions, kea, path, props, reducers, selectors } from 'kea'
import { isTrendsFilter } from 'scenes/insights/sharedUtils'

import { ChartDisplayType, FilterType } from '~/types'

import type { insightsTableLogicType } from './insightsTableLogicType'

export type CalcColumnState = 'total' | 'average' | 'median'

export const insightsTableLogic = kea<insightsTableLogicType>([
    props(
        {} as {
            hasMathUniqueFilter: boolean
            filters: Partial<FilterType>
        }
    ),
    path(['scenes', 'insights', 'InsightsTable', 'insightsTableLogic']),
    actions({
        setCalcColumnState: (state: CalcColumnState) => ({ state }),
    }),
    reducers(({ props }) => ({
        calcColumnState: [
            (props.hasMathUniqueFilter ? 'average' : 'total') as CalcColumnState,
            {
                setCalcColumnState: (_, { state }) => state,
            },
        ],
    })),
    selectors(() => ({
        // Only allow table aggregation options when the math is total volume otherwise double counting will happen when the math is set to uniques
        // Except when view type is Table
        showTotalCount: [
            (_, p) => [p.filters],
            (filters: Partial<FilterType>) => {
                if (isTrendsFilter(filters) && filters.display == ChartDisplayType.ActionsTable) {
                    return true
                }
                return (
                    filters.actions?.every(
                        (entity) => entity.math === 'total' || entity.math === 'sum' || !entity.math
                    ) &&
                    filters.events?.every((entity) => entity.math === 'total' || entity.math === 'sum' || !entity.math)
                )
            },
        ],
    })),
])
