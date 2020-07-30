// Auto-generated with kea-typegen. DO NOT EDIT!

export interface dashboardsLogicType {
    key: any
    actionCreators: {
        addNewDashboard: () => {
            type: 'add new dashboard (frontend.src.scenes.dashboard.dashboardsLogic)'
            payload: {
                value: boolean
            }
        }
    }
    actionKeys: {
        'add new dashboard (frontend.src.scenes.dashboard.dashboardsLogic)': 'addNewDashboard'
    }
    actionTypes: {
        addNewDashboard: 'add new dashboard (frontend.src.scenes.dashboard.dashboardsLogic)'
    }
    actions: {
        addNewDashboard: () => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'dashboard', 'dashboardsLogic']
    pathString: 'frontend.src.scenes.dashboard.dashboardsLogic'
    propTypes: any
    props: Record<string, any>
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
