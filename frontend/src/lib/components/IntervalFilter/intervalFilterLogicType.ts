// Auto-generated with kea-typegen. DO NOT EDIT!

export interface intervalFilterLogicType {
    key: undefined
    actionCreators: {
        setIntervalFilter: (
            filter: any
        ) => {
            type: 'set interval filter (lib.components.IntervalFilter.intervalFilterLogic)'
            payload: { filter: any }
        }
        setDateFrom: (
            dateFrom: any
        ) => {
            type: 'set date from (lib.components.IntervalFilter.intervalFilterLogic)'
            payload: { dateFrom: any }
        }
    }
    actionKeys: {
        'set interval filter (lib.components.IntervalFilter.intervalFilterLogic)': 'setIntervalFilter'
        'set date from (lib.components.IntervalFilter.intervalFilterLogic)': 'setDateFrom'
    }
    actionTypes: {
        setIntervalFilter: 'set interval filter (lib.components.IntervalFilter.intervalFilterLogic)'
        setDateFrom: 'set date from (lib.components.IntervalFilter.intervalFilterLogic)'
    }
    actions: {
        setIntervalFilter: (filter: any) => void
        setDateFrom: (dateFrom: any) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: {
        interval: null
        dateFrom: null
    }
    events: any
    path: ['lib', 'components', 'IntervalFilter', 'intervalFilterLogic']
    pathString: 'lib.components.IntervalFilter.intervalFilterLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        interval: null
        dateFrom: null
    }
    reducerOptions: any
    reducers: {
        interval: (state: null, action: any, fullState: any) => null
        dateFrom: (state: null, action: any, fullState: any) => null
    }
    selector: (
        state: any
    ) => {
        interval: null
        dateFrom: null
    }
    selectors: {
        interval: (state: any, props: any) => null
        dateFrom: (state: any, props: any) => null
    }
    values: {
        interval: null
        dateFrom: null
    }
    _isKea: true
}
