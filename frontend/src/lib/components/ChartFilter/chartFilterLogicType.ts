// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic } from 'kea'

export interface chartFilterLogicType extends Logic {
    actionCreators: {
        setChartFilter: (
            filter: any
        ) => {
            type: 'set chart filter (lib.components.ChartFilter.chartFilterLogic)'
            payload: {
                filter: any
            }
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
    constants: {}
    defaults: {
        chartFilter: 'ActionsLineGraph'
    }
    events: {}
    key: undefined
    listeners: {}
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
    reducerOptions: {}
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
    sharedListeners: {}
    values: {
        chartFilter: 'ActionsLineGraph'
    }
    _isKea: true
    _isKeaWithKey: false
}
