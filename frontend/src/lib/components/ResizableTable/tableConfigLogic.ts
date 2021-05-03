import { kea } from 'kea'
import { tableConfigLogicType } from './tableConfigLogicType'

export enum TableConfigStates {
    columnConfig = 'columnConfig', // Modal showing
    saving = 'saving', // Saving in progress
    success = 'success', // Save committed
    failure = 'failure', // Save failure
}

export type TableConfigStateType = `${TableConfigStates}` | null

export const tableConfigLogic = kea<tableConfigLogicType<TableConfigStateType>>({
    actions: {
        setState: (state: TableConfigStateType) => ({ state }),
    },
    reducers: {
        state: [
            null as TableConfigStateType,
            {
                setState: (_, { state }) => state,
            },
        ],
    },
})
