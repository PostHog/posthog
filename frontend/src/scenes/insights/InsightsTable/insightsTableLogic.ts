import { kea } from 'kea'
import { insightsTableLogicType } from './insightsTableLogicType'

export type CalcColumnState = 'total' | 'average' | 'median'

export const insightsTableLogic = kea<insightsTableLogicType<CalcColumnState>>({
    props: {} as {
        hasUniqueFilter: boolean
    },
    actions: {
        setCalcColumnState: (state: CalcColumnState) => ({ state }),
    },
    reducers: ({ props }) => ({
        calcColumnState: [
            (props.hasUniqueFilter ? 'average' : 'total') as CalcColumnState,
            {
                setCalcColumnState: (_, { state }) => state,
            },
        ],
    }),
})
