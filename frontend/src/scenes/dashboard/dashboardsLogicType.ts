// Auto-generated with kea-typegen. DO NOT EDIT!

export interface dashboardsLogicType {
    key: any
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
        addNewDashboard: () => {
            type: 'add new dashboard (scenes.dashboard.dashboardsLogic)'
            payload: {
                value: boolean
            }
        }
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['scenes', 'dashboard', 'dashboardsLogic']
    pathString: 'scenes.dashboard.dashboardsLogic'
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
