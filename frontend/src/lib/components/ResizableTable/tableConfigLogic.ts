import { kea } from 'kea'
import { tableConfigLogicType } from './tableConfigLogicType'

type StateType = 'columnConfig' | null

export const tableConfigLogic = kea<tableConfigLogicType<StateType>>({
    actions: {
        setState: (state: StateType) => ({ state }),
    },
    reducers: {
        state: [
            null as StateType,
            {
                setState: (_, { state }) => state,
            },
        ],
    },
})
