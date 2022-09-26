import { kea } from 'kea'
import { FilterType } from '~/types'
import type { insightsTableLogicType } from './insightsTableLogicType'

export type CalcColumnState = 'total' | 'average' | 'median'

export const insightsTableLogic = kea<insightsTableLogicType>({
    path: ['scenes', 'insights', 'InsightsTable', 'insightsTableLogic'],
    props: {} as {
        hasMathUniqueFilter: boolean
        filters: Partial<FilterType>
    },
    actions: {
        setCalcColumnState: (state: CalcColumnState) => ({ state }),
    },
    reducers: ({ props }) => ({
        calcColumnState: [
            (props.hasMathUniqueFilter ? 'average' : 'total') as CalcColumnState,
            {
                setCalcColumnState: (_, { state }) => state,
            },
        ],
    }),
    selectors: () => ({
        // Only allow table aggregation options when the math is total volume otherwise double counting will happen when the math is set to uniques
        showTotalCount: [
            () => [(_, props) => props.filters],
            (filters) => {
                return (
                    filters.actions?.every(
                        (entity) => entity.math === 'total' || entity.math === 'sum' || !entity.math
                    ) &&
                    filters.events?.every((entity) => entity.math === 'total' || entity.math === 'sum' || !entity.math)
                )
            },
        ],
    }),
})
