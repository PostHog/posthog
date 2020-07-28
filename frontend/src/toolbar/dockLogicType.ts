// Auto-generated with kea-typegen. DO NOT EDIT!

export interface dockLogicType {
    key: any
    actionCreators: {
        button: () => {
            type: 'button (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        dock: () => {
            type: 'dock (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        hideButton: () => {
            type: 'hide button (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        update: () => {
            type: 'update (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        buttonAnimated: () => {
            type: 'button animated (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        buttonFaded: () => {
            type: 'button faded (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        dockAnimated: () => {
            type: 'dock animated (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        dockFaded: () => {
            type: 'dock faded (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        hideButtonAnimated: () => {
            type: 'hide button animated (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        setMode: (
            mode: any,
            update?: any
        ) => {
            type: 'set mode (toolbar.dockLogic)'
            payload: { mode: any; update: boolean; windowWidth: number; windowHeight: number }
        }
    }
    actionKeys: {
        'button (toolbar.dockLogic)': 'button'
        'dock (toolbar.dockLogic)': 'dock'
        'hide button (toolbar.dockLogic)': 'hideButton'
        'update (toolbar.dockLogic)': 'update'
        'button animated (toolbar.dockLogic)': 'buttonAnimated'
        'button faded (toolbar.dockLogic)': 'buttonFaded'
        'dock animated (toolbar.dockLogic)': 'dockAnimated'
        'dock faded (toolbar.dockLogic)': 'dockFaded'
        'hide button animated (toolbar.dockLogic)': 'hideButtonAnimated'
        'set mode (toolbar.dockLogic)': 'setMode'
    }
    actionTypes: {
        button: 'button (toolbar.dockLogic)'
        dock: 'dock (toolbar.dockLogic)'
        hideButton: 'hide button (toolbar.dockLogic)'
        update: 'update (toolbar.dockLogic)'
        buttonAnimated: 'button animated (toolbar.dockLogic)'
        buttonFaded: 'button faded (toolbar.dockLogic)'
        dockAnimated: 'dock animated (toolbar.dockLogic)'
        dockFaded: 'dock faded (toolbar.dockLogic)'
        hideButtonAnimated: 'hide button animated (toolbar.dockLogic)'
        setMode: 'set mode (toolbar.dockLogic)'
    }
    actions: {
        button: () => {
            type: 'button (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        dock: () => {
            type: 'dock (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        hideButton: () => {
            type: 'hide button (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        update: () => {
            type: 'update (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        buttonAnimated: () => {
            type: 'button animated (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        buttonFaded: () => {
            type: 'button faded (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        dockAnimated: () => {
            type: 'dock animated (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        dockFaded: () => {
            type: 'dock faded (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        hideButtonAnimated: () => {
            type: 'hide button animated (toolbar.dockLogic)'
            payload: {
                value: boolean
            }
        }
        setMode: (
            mode: any,
            update?: any
        ) => {
            type: 'set mode (toolbar.dockLogic)'
            payload: { mode: any; update: boolean; windowWidth: number; windowHeight: number }
        }
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['toolbar', 'dockLogic']
    pathString: 'toolbar.dockLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        windowWidth: number
        windowHeight: number
        windowScroll: number
        mode: string
        lastMode: string
        dockStatus: string
        buttonStatus: string
    }
    reducerOptions: any
    reducers: {
        windowWidth: (state: number, action: any, fullState: any) => number
        windowHeight: (state: number, action: any, fullState: any) => number
        windowScroll: (state: number, action: any, fullState: any) => number
        mode: (state: string, action: any, fullState: any) => string
        lastMode: (state: string, action: any, fullState: any) => string
        dockStatus: (state: string, action: any, fullState: any) => string
        buttonStatus: (state: string, action: any, fullState: any) => string
    }
    selector: (
        state: any
    ) => {
        windowWidth: number
        windowHeight: number
        windowScroll: number
        mode: string
        lastMode: string
        dockStatus: string
        buttonStatus: string
    }
    selectors: {
        windowWidth: (state: any, props: any) => number
        windowHeight: (state: any, props: any) => number
        windowScroll: (state: any, props: any) => number
        mode: (state: any, props: any) => string
        lastMode: (state: any, props: any) => string
        dockStatus: (state: any, props: any) => string
        buttonStatus: (state: any, props: any) => string
    }
    values: {
        windowWidth: number
        windowHeight: number
        windowScroll: number
        mode: string
        lastMode: string
        dockStatus: string
        buttonStatus: string
    }
    _isKea: true
}
