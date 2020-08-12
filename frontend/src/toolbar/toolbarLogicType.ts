// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic, BreakPointFunction } from 'kea'

export interface toolbarLogicType extends Logic {
    actionCreators: {
        authenticate: () => {
            type: 'authenticate (toolbar.toolbarLogic)'
            payload: {
                value: boolean
            }
        }
        logout: () => {
            type: 'logout (toolbar.toolbarLogic)'
            payload: {
                value: boolean
            }
        }
    }
    actionKeys: {
        'authenticate (toolbar.toolbarLogic)': 'authenticate'
        'logout (toolbar.toolbarLogic)': 'logout'
    }
    actionTypes: {
        authenticate: 'authenticate (toolbar.toolbarLogic)'
        logout: 'logout (toolbar.toolbarLogic)'
    }
    actions: {
        authenticate: () => void
        logout: () => void
    }
    constants: {}
    defaults: {
        rawApiURL: string
        rawJsURL: string
        temporaryToken: string | null
        actionId: number | null
        userIntent: string | null
    }
    events: {
        afterMount: () => void
    }
    key: undefined
    listeners: {
        authenticate: ((
            payload: {
                value: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'authenticate (toolbar.toolbarLogic)'
                payload: {
                    value: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        logout: ((
            payload: {
                value: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'logout (toolbar.toolbarLogic)'
                payload: {
                    value: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
    }
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
    reducerOptions: {}
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
    sharedListeners: {}
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
    _isKeaWithKey: false
    __keaTypeGenInternalSelectorTypes: {
        apiURL: (arg1: string) => string
        jsURL: (arg1: string) => string
        isAuthenticated: (arg1: string | null) => boolean
    }
}
