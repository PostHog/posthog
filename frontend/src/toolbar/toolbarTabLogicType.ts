// Auto-generated with kea-typegen. DO NOT EDIT!

export interface toolbarTabLogicType<ToolbarTab> {
    key: any
    actionCreators: {
        setTab: (
            tab: ToolbarTab | string
        ) => {
            type: 'set tab (frontend.src.toolbar.toolbarTabLogic)'
            payload: { tab: string }
        }
    }
    actionKeys: {
        'set tab (frontend.src.toolbar.toolbarTabLogic)': 'setTab'
    }
    actionTypes: {
        setTab: 'set tab (frontend.src.toolbar.toolbarTabLogic)'
    }
    actions: {
        setTab: (tab: ToolbarTab | string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'toolbar', 'toolbarTabLogic']
    pathString: 'frontend.src.toolbar.toolbarTabLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        tab: ToolbarTab
    }
    reducerOptions: any
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
    values: {
        tab: ToolbarTab
    }
    _isKea: true
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
