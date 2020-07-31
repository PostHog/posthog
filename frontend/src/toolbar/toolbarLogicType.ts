// Auto-generated with kea-typegen. DO NOT EDIT!

export interface toolbarLogicType {
    key: undefined
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
        authenticate: () => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: {
        rawApiURL: string
        rawJsURL: string
        temporaryToken: string | null
        actionId: number | null
        userIntent: string | null
    }
    events: any
    path: ['toolbar', 'toolbarLogic']
    pathString: 'toolbar.toolbarLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        rawApiURL: string
        rawJsURL: string
        temporaryToken: string | null
        actionId: number | null
        userIntent: string | null
    }
    reducerOptions: any
    reducers: {
        rawApiURL: (state: string, action: any, fullState: any) => string
        rawJsURL: (state: string, action: any, fullState: any) => string
        temporaryToken: (state: string | null, action: any, fullState: any) => string | null
        actionId: (state: number | null, action: any, fullState: any) => number | null
        userIntent: (state: string | null, action: any, fullState: any) => string | null
    }
    selector: (
        state: any
    ) => {
        rawApiURL: string
        rawJsURL: string
        temporaryToken: string | null
        actionId: number | null
        userIntent: string | null
    }
    selectors: {
        rawApiURL: (state: any, props: any) => string
        rawJsURL: (state: any, props: any) => string
        temporaryToken: (state: any, props: any) => string | null
        actionId: (state: any, props: any) => number | null
        userIntent: (state: any, props: any) => string | null
        apiURL: (state: any, props: any) => string
        jsURL: (state: any, props: any) => string
        isAuthenticated: (state: any, props: any) => boolean
    }
    values: {
        rawApiURL: string
        rawJsURL: string
        temporaryToken: string | null
        actionId: number | null
        userIntent: string | null
        apiURL: string
        jsURL: string
        isAuthenticated: boolean
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        apiURL: (arg1: string) => string
        jsURL: (arg1: string) => string
        isAuthenticated: (arg1: string | null) => boolean
    }
}
