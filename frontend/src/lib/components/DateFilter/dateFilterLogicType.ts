// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic } from 'kea'

export interface dateFilterLogicType extends Logic {
    actionCreators: {
        setDates: (
            dateFrom: any,
            dateTo: any
        ) => {
            type: 'set dates (lib.components.DateFilter.dateFilterLogic)'
            payload: {
                dateFrom: any
                dateTo: any
            }
        }
    }
    actionKeys: {
        'set dates (lib.components.DateFilter.dateFilterLogic)': 'setDates'
    }
    actionTypes: {
        setDates: 'set dates (lib.components.DateFilter.dateFilterLogic)'
    }
    actions: {
        setDates: (dateFrom: any, dateTo: any) => void
    }
    constants: {}
    defaults: {
        dates: {}
    }
    events: {}
    key: undefined
    listeners: {}
    path: ['lib', 'components', 'DateFilter', 'dateFilterLogic']
    pathString: 'lib.components.DateFilter.dateFilterLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        dates: {}
    }
    reducerOptions: {}
    reducers: {
        dates: (state: {}, action: any, fullState: any) => {}
    }
    selector: (
        state: any
    ) => {
        dates: {}
    }
    selectors: {
        dates: (state: any, props: any) => {}
    }
    sharedListeners: {}
    values: {
        dates: {}
    }
    _isKea: true
    _isKeaWithKey: false
}
