// Auto-generated with kea-typegen. DO NOT EDIT!

export interface dashboardsLogicType {
    key: undefined
    actionCreators: {
        addNewDashboard: () => {
            type: 'add new dashboard (scenes.dashboard.dashboardsLogic)'
            payload: {
                value: boolean
            }
        }
    }
    actionKeys: {
        'add new dashboard (scenes.dashboard.dashboardsLogic)': 'addNewDashboard'
    }
    actionTypes: {
        addNewDashboard: 'add new dashboard (scenes.dashboard.dashboardsLogic)'
    }
    actions: {
        addNewDashboard: () => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: {}
    events: any
    path: ['scenes', 'dashboard', 'dashboardsLogic']
    pathString: 'scenes.dashboard.dashboardsLogic'
    props: Record<string, unknown>
    reducer: (state: any, action: () => any, fullState: any) => {}
    reducerOptions: any
    reducers: {}
    selector: (state: any) => {}
    selectors: {
        dashboards: (state: any, props: any) => any
    }
    values: {
        dashboards: any
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        dashboards: (arg1: any) => any
    }
}
