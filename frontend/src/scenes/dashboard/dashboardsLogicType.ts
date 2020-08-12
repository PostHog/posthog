// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic, BreakPointFunction } from 'kea'

export interface dashboardsLogicType extends Logic {
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
    constants: {}
    defaults: {}
    events: {}
    key: undefined
    listeners: {
        addNewDashboard: ((
            payload: {
                value: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'add new dashboard (scenes.dashboard.dashboardsLogic)'
                payload: {
                    value: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
    }
    path: ['scenes', 'dashboard', 'dashboardsLogic']
    pathString: 'scenes.dashboard.dashboardsLogic'
    props: Record<string, unknown>
    reducer: (state: any, action: () => any, fullState: any) => {}
    reducerOptions: {}
    reducers: {}
    selector: (state: any) => {}
    selectors: {
        dashboards: (state: any, props: any) => any
    }
    sharedListeners: {}
    values: {
        dashboards: any
    }
    _isKea: true
    _isKeaWithKey: false
    __keaTypeGenInternalSelectorTypes: {
        dashboards: (arg1: any) => any
    }
}
