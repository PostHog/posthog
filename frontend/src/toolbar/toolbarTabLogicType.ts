// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic } from 'kea'

export interface toolbarTabLogicType<ToolbarTab> extends Logic {
    actionCreators: {
        setTab: (
            tab: ToolbarTab | string
        ) => {
            type: 'set tab (toolbar.toolbarTabLogic)'
            payload: {
                tab: string
            }
        }
    }
    actionKeys: {
        'set tab (toolbar.toolbarTabLogic)': 'setTab'
    }
    actionTypes: {
        setTab: 'set tab (toolbar.toolbarTabLogic)'
    }
    actions: {
        setTab: (tab: ToolbarTab | string) => void
    }
    constants: {}
    defaults: {
        tab: ToolbarTab
    }
    events: {}
    key: undefined
    listeners: {}
    path: ['toolbar', 'toolbarTabLogic']
    pathString: 'toolbar.toolbarTabLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        tab: ToolbarTab
    }
    reducerOptions: {}
    reducers: {
        tab: (state: ToolbarTab, action: any, fullState: any) => ToolbarTab
    }
    selector: (
        state: any
    ) => {
        tab: ToolbarTab
    }
    selectors: {
        tab: (state: any, props: any) => ToolbarTab
    }
    sharedListeners: {}
    values: {
        tab: ToolbarTab
    }
    _isKea: true
    _isKeaWithKey: false
    __keaTypeGenInternalReducerActions: {
        'button (toolbar.dockLogic)': () => {
            type: 'button (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        'dock (toolbar.dockLogic)': () => {
            type: 'dock (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
    }
}
