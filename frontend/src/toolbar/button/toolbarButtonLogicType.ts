// Auto-generated with kea-typegen. DO NOT EDIT!

export interface toolbarButtonLogicType {
    key: any
    actionCreators: {
        showHeatmapInfo: () => {
            type: 'show heatmap info (frontend.src.toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        hideHeatmapInfo: () => {
            type: 'hide heatmap info (frontend.src.toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        showActionsInfo: () => {
            type: 'show actions info (frontend.src.toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        hideActionsInfo: () => {
            type: 'hide actions info (frontend.src.toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        showStats: () => {
            type: 'show stats (frontend.src.toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        hideStats: () => {
            type: 'hide stats (frontend.src.toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        setExtensionPercentage: (
            percentage: number
        ) => {
            type: 'set extension percentage (frontend.src.toolbar.button.toolbarButtonLogic)'
            payload: { percentage: number }
        }
        saveDragPosition: (
            x: number,
            y: number
        ) => {
            type: 'save drag position (frontend.src.toolbar.button.toolbarButtonLogic)'
            payload: { x: number; y: number }
        }
        saveHeatmapPosition: (
            x: number,
            y: number
        ) => {
            type: 'save heatmap position (frontend.src.toolbar.button.toolbarButtonLogic)'
            payload: { x: number; y: number }
        }
        saveActionsPosition: (
            x: number,
            y: number
        ) => {
            type: 'save actions position (frontend.src.toolbar.button.toolbarButtonLogic)'
            payload: { x: number; y: number }
        }
        saveStatsPosition: (
            x: number,
            y: number
        ) => {
            type: 'save stats position (frontend.src.toolbar.button.toolbarButtonLogic)'
            payload: { x: number; y: number }
        }
    }
    actionKeys: {
        'show heatmap info (frontend.src.toolbar.button.toolbarButtonLogic)': 'showHeatmapInfo'
        'hide heatmap info (frontend.src.toolbar.button.toolbarButtonLogic)': 'hideHeatmapInfo'
        'show actions info (frontend.src.toolbar.button.toolbarButtonLogic)': 'showActionsInfo'
        'hide actions info (frontend.src.toolbar.button.toolbarButtonLogic)': 'hideActionsInfo'
        'show stats (frontend.src.toolbar.button.toolbarButtonLogic)': 'showStats'
        'hide stats (frontend.src.toolbar.button.toolbarButtonLogic)': 'hideStats'
        'set extension percentage (frontend.src.toolbar.button.toolbarButtonLogic)': 'setExtensionPercentage'
        'save drag position (frontend.src.toolbar.button.toolbarButtonLogic)': 'saveDragPosition'
        'save heatmap position (frontend.src.toolbar.button.toolbarButtonLogic)': 'saveHeatmapPosition'
        'save actions position (frontend.src.toolbar.button.toolbarButtonLogic)': 'saveActionsPosition'
        'save stats position (frontend.src.toolbar.button.toolbarButtonLogic)': 'saveStatsPosition'
    }
    actionTypes: {
        showHeatmapInfo: 'show heatmap info (frontend.src.toolbar.button.toolbarButtonLogic)'
        hideHeatmapInfo: 'hide heatmap info (frontend.src.toolbar.button.toolbarButtonLogic)'
        showActionsInfo: 'show actions info (frontend.src.toolbar.button.toolbarButtonLogic)'
        hideActionsInfo: 'hide actions info (frontend.src.toolbar.button.toolbarButtonLogic)'
        showStats: 'show stats (frontend.src.toolbar.button.toolbarButtonLogic)'
        hideStats: 'hide stats (frontend.src.toolbar.button.toolbarButtonLogic)'
        setExtensionPercentage: 'set extension percentage (frontend.src.toolbar.button.toolbarButtonLogic)'
        saveDragPosition: 'save drag position (frontend.src.toolbar.button.toolbarButtonLogic)'
        saveHeatmapPosition: 'save heatmap position (frontend.src.toolbar.button.toolbarButtonLogic)'
        saveActionsPosition: 'save actions position (frontend.src.toolbar.button.toolbarButtonLogic)'
        saveStatsPosition: 'save stats position (frontend.src.toolbar.button.toolbarButtonLogic)'
    }
    actions: {
        showHeatmapInfo: () => void
        hideHeatmapInfo: () => void
        showActionsInfo: () => void
        hideActionsInfo: () => void
        showStats: () => void
        hideStats: () => void
        setExtensionPercentage: (percentage: number) => void
        saveDragPosition: (x: number, y: number) => void
        saveHeatmapPosition: (x: number, y: number) => void
        saveActionsPosition: (x: number, y: number) => void
        saveStatsPosition: (x: number, y: number) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'toolbar', 'button', 'toolbarButtonLogic']
    pathString: 'frontend.src.toolbar.button.toolbarButtonLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        windowHeight: number
        windowWidth: number
        heatmapInfoVisible: boolean
        actionsInfoVisible: boolean
        statsVisible: boolean
        extensionPercentage: number
        lastDragPosition: null | {
            x: number
            y: number
        }
        heatmapPosition: {
            x: number
            y: number
        }
        actionsPosition: {
            x: number
            y: number
        }
        statsPosition: {
            x: number
            y: number
        }
    }
    reducerOptions: any
    reducers: {
        windowHeight: (state: number, action: any, fullState: any) => number
        windowWidth: (state: number, action: any, fullState: any) => number
        heatmapInfoVisible: (state: boolean, action: any, fullState: any) => boolean
        actionsInfoVisible: (state: boolean, action: any, fullState: any) => boolean
        statsVisible: (state: boolean, action: any, fullState: any) => boolean
        extensionPercentage: (state: number, action: any, fullState: any) => number
        lastDragPosition: (
            state: null | {
                x: number
                y: number
            },
            action: any,
            fullState: any
        ) => null | {
            x: number
            y: number
        }
        heatmapPosition: (
            state: {
                x: number
                y: number
            },
            action: any,
            fullState: any
        ) => {
            x: number
            y: number
        }
        actionsPosition: (
            state: {
                x: number
                y: number
            },
            action: any,
            fullState: any
        ) => {
            x: number
            y: number
        }
        statsPosition: (
            state: {
                x: number
                y: number
            },
            action: any,
            fullState: any
        ) => {
            x: number
            y: number
        }
    }
    selector: (
        state: any
    ) => {
        windowHeight: number
        windowWidth: number
        heatmapInfoVisible: boolean
        actionsInfoVisible: boolean
        statsVisible: boolean
        extensionPercentage: number
        lastDragPosition: null | {
            x: number
            y: number
        }
        heatmapPosition: {
            x: number
            y: number
        }
        actionsPosition: {
            x: number
            y: number
        }
        statsPosition: {
            x: number
            y: number
        }
    }
    selectors: {
        windowHeight: (state: any, props: any) => number
        windowWidth: (state: any, props: any) => number
        heatmapInfoVisible: (state: any, props: any) => boolean
        actionsInfoVisible: (state: any, props: any) => boolean
        statsVisible: (state: any, props: any) => boolean
        extensionPercentage: (state: any, props: any) => number
        lastDragPosition: (
            state: any,
            props: any
        ) => null | {
            x: number
            y: number
        }
        heatmapPosition: (
            state: any,
            props: any
        ) => {
            x: number
            y: number
        }
        actionsPosition: (
            state: any,
            props: any
        ) => {
            x: number
            y: number
        }
        statsPosition: (
            state: any,
            props: any
        ) => {
            x: number
            y: number
        }
        dragPosition: (state: any, props: any) => { x: number; y: number }
        toolbarListVerticalPadding: (state: any, props: any) => number
        dockButtonOnTop: (state: any, props: any) => boolean
        side: (state: any, props: any) => 'left' | 'right'
        closeDistance: (state: any, props: any) => number
        closeRotation: (state: any, props: any) => number
        inspectExtensionPercentage: (state: any, props: any) => number
        heatmapExtensionPercentage: (state: any, props: any) => number
        heatmapWindowVisible: (state: any, props: any) => boolean
        actionsExtensionPercentage: (state: any, props: any) => number
        actionsWindowVisible: (state: any, props: any) => boolean
        statsExtensionPercentage: (state: any, props: any) => number
    }
    values: {
        windowHeight: number
        windowWidth: number
        heatmapInfoVisible: boolean
        actionsInfoVisible: boolean
        statsVisible: boolean
        extensionPercentage: number
        lastDragPosition: null | {
            x: number
            y: number
        }
        heatmapPosition: {
            x: number
            y: number
        }
        actionsPosition: {
            x: number
            y: number
        }
        statsPosition: {
            x: number
            y: number
        }
        dragPosition: { x: number; y: number }
        toolbarListVerticalPadding: number
        dockButtonOnTop: boolean
        side: 'left' | 'right'
        closeDistance: number
        closeRotation: number
        inspectExtensionPercentage: number
        heatmapExtensionPercentage: number
        heatmapWindowVisible: boolean
        actionsExtensionPercentage: number
        actionsWindowVisible: boolean
        statsExtensionPercentage: number
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        dragPosition: (
            arg1: {
                x: number
                y: number
            } | null,
            arg2: number,
            arg3: number
        ) => { x: number; y: number }
        toolbarListVerticalPadding: (
            arg1: {
                x: number
                y: number
            },
            arg2: number
        ) => number
        dockButtonOnTop: (
            arg1: {
                x: number
                y: number
            },
            arg2: number
        ) => boolean
        side: (
            arg1: {
                x: number
                y: number
            },
            arg2: number
        ) => 'left' | 'right'
        closeDistance: (
            arg1: {
                x: number
                y: number
            },
            arg2: number
        ) => number
        closeRotation: (
            arg1: {
                x: number
                y: number
            },
            arg2: number
        ) => number
        inspectExtensionPercentage: (arg1: boolean, arg2: number) => number
        heatmapExtensionPercentage: (arg1: boolean, arg2: number) => number
        heatmapWindowVisible: (arg1: boolean, arg2: boolean) => boolean
        actionsExtensionPercentage: (arg1: boolean, arg2: number) => number
        actionsWindowVisible: (arg1: boolean, arg2: boolean) => boolean
        statsExtensionPercentage: (arg1: boolean, arg2: number) => number
    }
    __keaTypeGenInternalReducerActions: {
        'disable heatmap (toolbar.elements.heatmapLogic)': () => {
            type: 'disable heatmap (toolbar.elements.heatmapLogic)'
            payload: {
                value: boolean
            }
        }
        'enable heatmap (toolbar.elements.heatmapLogic)': () => {
            type: 'enable heatmap (toolbar.elements.heatmapLogic)'
            payload: {
                value: boolean
            }
        }
        'show button actions (toolbar.actions.actionsTabLogic)': () => {
            type: 'show button actions (toolbar.actions.actionsTabLogic)'
            payload: {
                value: boolean
            }
        }
        'hide button actions (toolbar.actions.actionsTabLogic)': () => {
            type: 'hide button actions (toolbar.actions.actionsTabLogic)'
            payload: {
                value: boolean
            }
        }
    }
}
