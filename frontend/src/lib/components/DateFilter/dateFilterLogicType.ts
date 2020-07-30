// Auto-generated with kea-typegen. DO NOT EDIT!

export interface dateFilterLogicType {
    key: any
    actionCreators: {
        setDates: (
            dateFrom: any,
            dateTo: any
        ) => {
            type: 'set dates (frontend.src.lib.components.DateFilter.dateFilterLogic)'
            payload: { dateFrom: any; dateTo: any }
        }
    }
    actionKeys: {
        'set dates (frontend.src.lib.components.DateFilter.dateFilterLogic)': 'setDates'
    }
    actionTypes: {
        setDates: 'set dates (frontend.src.lib.components.DateFilter.dateFilterLogic)'
    }
    actions: {
        setDates: (dateFrom: any, dateTo: any) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'lib', 'components', 'DateFilter', 'dateFilterLogic']
    pathString: 'frontend.src.lib.components.DateFilter.dateFilterLogic'
    propTypes: any
    props: Record<string, any>
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
