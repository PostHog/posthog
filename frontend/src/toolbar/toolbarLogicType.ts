// Auto-generated with kea-typegen. DO NOT EDIT!

export interface toolbarLogicType {
    key: any
    actionCreators: {
        authenticate: () => {
            type: 'authenticate (toolbar.toolbarLogic)'
            payload: {
                value: boolean
            }
        }
    }
    actionKeys: {
        'authenticate (toolbar.toolbarLogic)': 'authenticate'
    }
    actionTypes: {
        authenticate: 'authenticate (toolbar.toolbarLogic)'
    }
    actions: {
        authenticate: () => {
            type: 'authenticate (toolbar.toolbarLogic)'
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
    path: ['toolbar', 'toolbarLogic']
    pathString: 'toolbar.toolbarLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        rawApiURL: any
        rawJsURL: any
        temporaryToken: any
        actionId: any
        userIntent: any
    }
    reducerOptions: any
    reducers: {
        rawApiURL: (state: any, action: any, fullState: any) => any
        rawJsURL: (state: any, action: any, fullState: any) => any
        temporaryToken: (state: any, action: any, fullState: any) => any
        actionId: (state: any, action: any, fullState: any) => any
        userIntent: (state: any, action: any, fullState: any) => any
    }
    selector: (
        state: any
    ) => {
        rawApiURL: any
        rawJsURL: any
        temporaryToken: any
        actionId: any
        userIntent: any
    }
    selectors: {
        rawApiURL: (state: any, props: any) => any
        rawJsURL: (state: any, props: any) => any
        temporaryToken: (state: any, props: any) => any
        actionId: (state: any, props: any) => any
        userIntent: (state: any, props: any) => any
        apiURL: (state: any, props: any) => string
        jsURL: (state: any, props: any) => string
        isAuthenticated: (state: any, props: any) => boolean
    }
    values: {
        rawApiURL: any
        rawJsURL: any
        temporaryToken: any
        actionId: any
        userIntent: any
        apiURL: string
        jsURL: string
        isAuthenticated: boolean
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        apiURL: (arg1: any) => string
        jsURL: (arg1: any) => string
        isAuthenticated: (arg1: any) => boolean
    }
}
