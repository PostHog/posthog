// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic, BreakPointFunction } from 'kea'

export interface saveToDashboardModalLogicType extends Logic {
    actionCreators: {
        addNewDashboard: () => {
            type: 'add new dashboard (lib.components.SaveToDashboard.SaveToDashboardModal)'
            payload: {
                value: boolean
            }
        }
    }
    actionKeys: {
        'add new dashboard (lib.components.SaveToDashboard.SaveToDashboardModal)': 'addNewDashboard'
    }
    actionTypes: {
        addNewDashboard: 'add new dashboard (lib.components.SaveToDashboard.SaveToDashboardModal)'
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
                type: 'add new dashboard (lib.components.SaveToDashboard.SaveToDashboardModal)'
                payload: {
                    value: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
    }
    path: ['lib', 'components', 'SaveToDashboard', 'SaveToDashboardModal']
    pathString: 'lib.components.SaveToDashboard.SaveToDashboardModal'
    props: Record<string, unknown>
    reducer: (state: any, action: () => any, fullState: any) => {}
    reducerOptions: {}
    reducers: {}
    selector: (state: any) => {}
    selectors: {}
    sharedListeners: {}
    values: {}
    _isKea: true
    _isKeaWithKey: false
}
