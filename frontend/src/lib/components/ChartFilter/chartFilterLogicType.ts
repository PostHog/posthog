// Auto-generated with kea-typegen. DO NOT EDIT!

export interface chartFilterLogicType {
    key: any
    actionCreators: {
        setChartFilter: (
            filter: any
        ) => {
            type: 'set chart filter (frontend.src.lib.components.ChartFilter.chartFilterLogic)'
            payload: { filter: any }
        }
    }
    actionKeys: {
        'set chart filter (frontend.src.lib.components.ChartFilter.chartFilterLogic)': 'setChartFilter'
    }
    actionTypes: {
        setChartFilter: 'set chart filter (frontend.src.lib.components.ChartFilter.chartFilterLogic)'
    }
    actions: {
        setChartFilter: (filter: any) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'lib', 'components', 'ChartFilter', 'chartFilterLogic']
    pathString: 'frontend.src.lib.components.ChartFilter.chartFilterLogic'
    propTypes: any
    props: Record<string, any>
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
