import { kea } from 'kea'
import { insightsTableLogicType } from './insightsTableLogicType'

export type CalcColumnState = 'total' | 'average' | 'median'

export const insightsTableLogic = kea<insightsTableLogicType<CalcColumnState>>({
    props: {} as {
        hasMathUniqueFilter: boolean
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
})
