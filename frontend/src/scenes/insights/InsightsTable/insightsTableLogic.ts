import { kea } from 'kea'
import { insightsTableLogicType } from './insightsTableLogicType'

export type CalcColumnState = 'total' | 'average' | 'median'

export const insightsTableLogic = kea<insightsTableLogicType<CalcColumnState>>({
    actions: {
        setCalcColumnState: (state: CalcColumnState) => ({ state }),
    },
    reducers: {
        calcColumnState: [
            'total' as CalcColumnState,
            {
                setCalcColumnState: (_, { state }) => state,
            },
        ],
    },
})
