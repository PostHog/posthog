// Auto-generated with kea-typegen. DO NOT EDIT!

export interface chartFilterLogicType {
    key: undefined
    actionCreators: {
        setChartFilter: (
            filter: any
        ) => {
            type: 'set chart filter (lib.components.ChartFilter.chartFilterLogic)'
            payload: { filter: any }
        }
    }
    actionKeys: {
        'set chart filter (lib.components.ChartFilter.chartFilterLogic)': 'setChartFilter'
    }
    actionTypes: {
        setChartFilter: 'set chart filter (lib.components.ChartFilter.chartFilterLogic)'
    }
    actions: {
        setChartFilter: (filter: any) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: {
        chartFilter: 'ActionsLineGraph'
    }
    events: any
    path: ['lib', 'components', 'ChartFilter', 'chartFilterLogic']
    pathString: 'lib.components.ChartFilter.chartFilterLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        chartFilter: 'ActionsLineGraph'
    }
    reducerOptions: any
    reducers: {
        chartFilter: (state: 'ActionsLineGraph', action: any, fullState: any) => 'ActionsLineGraph'
    }
    selector: (
        state: any
    ) => {
        chartFilter: 'ActionsLineGraph'
    }
    selectors: {
        chartFilter: (state: any, props: any) => 'ActionsLineGraph'
    }
    values: {
        chartFilter: 'ActionsLineGraph'
    }
    _isKea: true
}
