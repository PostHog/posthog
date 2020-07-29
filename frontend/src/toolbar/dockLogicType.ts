// Auto-generated with kea-typegen. DO NOT EDIT!

export interface dockLogicType<ToolbarMode, ToolbarAnimationState> {
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
            mode: ToolbarMode,
            update?: boolean
        ) => {
            type: 'set mode (toolbar.dockLogic)'
            payload: { mode: ToolbarMode; update: boolean; windowWidth: number; windowHeight: number }
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
            mode: ToolbarMode,
            update?: boolean
        ) => {
            type: 'set mode (toolbar.dockLogic)'
            payload: { mode: ToolbarMode; update: boolean; windowWidth: number; windowHeight: number }
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
        mode: ToolbarMode
        lastMode: ToolbarMode
        dockStatus: ToolbarAnimationState
        buttonStatus: ToolbarAnimationState
    }
    reducerOptions: any
    reducers: {
        windowWidth: (state: number, action: any, fullState: any) => number
        windowHeight: (state: number, action: any, fullState: any) => number
        windowScroll: (state: number, action: any, fullState: any) => number
        mode: (state: ToolbarMode, action: any, fullState: any) => ToolbarMode
        lastMode: (state: ToolbarMode, action: any, fullState: any) => ToolbarMode
        dockStatus: (state: ToolbarAnimationState, action: any, fullState: any) => ToolbarAnimationState
        buttonStatus: (state: ToolbarAnimationState, action: any, fullState: any) => ToolbarAnimationState
    }
    selector: (
        state: any
    ) => {
        windowWidth: number
        windowHeight: number
        windowScroll: number
        mode: ToolbarMode
        lastMode: ToolbarMode
        dockStatus: ToolbarAnimationState
        buttonStatus: ToolbarAnimationState
    }
    selectors: {
        windowWidth: (state: any, props: any) => number
        windowHeight: (state: any, props: any) => number
        windowScroll: (state: any, props: any) => number
        mode: (state: any, props: any) => ToolbarMode
        lastMode: (state: any, props: any) => ToolbarMode
        dockStatus: (state: any, props: any) => ToolbarAnimationState
        buttonStatus: (state: any, props: any) => ToolbarAnimationState
        isAnimating: (state: any, props: any) => boolean
        sidebarWidth: (state: any, props: any) => number
        padding: (state: any, props: any) => number
        bodyWidth: (state: any, props: any) => number
        zoom: (state: any, props: any) => number
        domZoom: (state: any, props: any) => number
        domPadding: (state: any, props: any) => number
        dockTopMargin: (state: any, props: any) => number
    }
    values: {
        windowWidth: number
        windowHeight: number
        windowScroll: number
        mode: ToolbarMode
        lastMode: ToolbarMode
        dockStatus: ToolbarAnimationState
        buttonStatus: ToolbarAnimationState
        isAnimating: boolean
        sidebarWidth: number
        padding: number
        bodyWidth: number
        zoom: number
        domZoom: number
        domPadding: number
        dockTopMargin: number
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        isAnimating: (arg1: ToolbarAnimationState, arg2: ToolbarAnimationState) => boolean
        padding: (arg1: number) => number
        bodyWidth: (arg1: number, arg2: number, arg3: number) => number
        zoom: (arg1: number, arg2: number) => number
        domZoom: (arg1: number, arg2: ToolbarMode) => number
        domPadding: (arg1: number, arg2: ToolbarMode) => number
        dockTopMargin: (arg1: number) => number
    }
}
