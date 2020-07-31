// Auto-generated with kea-typegen. DO NOT EDIT!

export interface dateFilterLogicType {
    key: undefined
    actionCreators: {
        setDates: (
            dateFrom: any,
            dateTo: any
        ) => {
            type: 'set dates (lib.components.DateFilter.dateFilterLogic)'
            payload: { dateFrom: any; dateTo: any }
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
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: {
        dates: {}
    }
    events: any
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
    reducerOptions: any
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
    values: {
        dates: {}
    }
    _isKea: true
}
