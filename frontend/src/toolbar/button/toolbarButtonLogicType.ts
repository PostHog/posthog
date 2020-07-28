// Auto-generated with kea-typegen. DO NOT EDIT!

export interface toolbarButtonLogicType {
    key: any
    actionCreators: {
        showHeatmapInfo: () => {
            type: 'show heatmap info (toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        hideHeatmapInfo: () => {
            type: 'hide heatmap info (toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        showActionsInfo: () => {
            type: 'show actions info (toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        hideActionsInfo: () => {
            type: 'hide actions info (toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        showStats: () => {
            type: 'show stats (toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        hideStats: () => {
            type: 'hide stats (toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        setExtensionPercentage: (
            percentage: any
        ) => {
            type: 'set extension percentage (toolbar.button.toolbarButtonLogic)'
            payload: { percentage: any }
        }
        saveDragPosition: (
            x: any,
            y: any
        ) => {
            type: 'save drag position (toolbar.button.toolbarButtonLogic)'
            payload: { x: any; y: any }
        }
        saveHeatmapPosition: (
            x: any,
            y: any
        ) => {
            type: 'save heatmap position (toolbar.button.toolbarButtonLogic)'
            payload: { x: any; y: any }
        }
        saveActionsPosition: (
            x: any,
            y: any
        ) => {
            type: 'save actions position (toolbar.button.toolbarButtonLogic)'
            payload: { x: any; y: any }
        }
        saveStatsPosition: (
            x: any,
            y: any
        ) => {
            type: 'save stats position (toolbar.button.toolbarButtonLogic)'
            payload: { x: any; y: any }
        }
    }
    actionKeys: {
        'show heatmap info (toolbar.button.toolbarButtonLogic)': 'showHeatmapInfo'
        'hide heatmap info (toolbar.button.toolbarButtonLogic)': 'hideHeatmapInfo'
        'show actions info (toolbar.button.toolbarButtonLogic)': 'showActionsInfo'
        'hide actions info (toolbar.button.toolbarButtonLogic)': 'hideActionsInfo'
        'show stats (toolbar.button.toolbarButtonLogic)': 'showStats'
        'hide stats (toolbar.button.toolbarButtonLogic)': 'hideStats'
        'set extension percentage (toolbar.button.toolbarButtonLogic)': 'setExtensionPercentage'
        'save drag position (toolbar.button.toolbarButtonLogic)': 'saveDragPosition'
        'save heatmap position (toolbar.button.toolbarButtonLogic)': 'saveHeatmapPosition'
        'save actions position (toolbar.button.toolbarButtonLogic)': 'saveActionsPosition'
        'save stats position (toolbar.button.toolbarButtonLogic)': 'saveStatsPosition'
    }
    actionTypes: {
        showHeatmapInfo: 'show heatmap info (toolbar.button.toolbarButtonLogic)'
        hideHeatmapInfo: 'hide heatmap info (toolbar.button.toolbarButtonLogic)'
        showActionsInfo: 'show actions info (toolbar.button.toolbarButtonLogic)'
        hideActionsInfo: 'hide actions info (toolbar.button.toolbarButtonLogic)'
        showStats: 'show stats (toolbar.button.toolbarButtonLogic)'
        hideStats: 'hide stats (toolbar.button.toolbarButtonLogic)'
        setExtensionPercentage: 'set extension percentage (toolbar.button.toolbarButtonLogic)'
        saveDragPosition: 'save drag position (toolbar.button.toolbarButtonLogic)'
        saveHeatmapPosition: 'save heatmap position (toolbar.button.toolbarButtonLogic)'
        saveActionsPosition: 'save actions position (toolbar.button.toolbarButtonLogic)'
        saveStatsPosition: 'save stats position (toolbar.button.toolbarButtonLogic)'
    }
    actions: {
        showHeatmapInfo: () => {
            type: 'show heatmap info (toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        hideHeatmapInfo: () => {
            type: 'hide heatmap info (toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        showActionsInfo: () => {
            type: 'show actions info (toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        hideActionsInfo: () => {
            type: 'hide actions info (toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        showStats: () => {
            type: 'show stats (toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        hideStats: () => {
            type: 'hide stats (toolbar.button.toolbarButtonLogic)'
            payload: {
                value: boolean
            }
        }
        setExtensionPercentage: (
            percentage: any
        ) => {
            type: 'set extension percentage (toolbar.button.toolbarButtonLogic)'
            payload: { percentage: any }
        }
        saveDragPosition: (
            x: any,
            y: any
        ) => {
            type: 'save drag position (toolbar.button.toolbarButtonLogic)'
            payload: { x: any; y: any }
        }
        saveHeatmapPosition: (
            x: any,
            y: any
        ) => {
            type: 'save heatmap position (toolbar.button.toolbarButtonLogic)'
            payload: { x: any; y: any }
        }
        saveActionsPosition: (
            x: any,
            y: any
        ) => {
            type: 'save actions position (toolbar.button.toolbarButtonLogic)'
            payload: { x: any; y: any }
        }
        saveStatsPosition: (
            x: any,
            y: any
        ) => {
            type: 'save stats position (toolbar.button.toolbarButtonLogic)'
            payload: { x: any; y: any }
        }
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['toolbar', 'button', 'toolbarButtonLogic']
    pathString: 'toolbar.button.toolbarButtonLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        heatmapInfoVisible: boolean
        actionsInfoVisible: boolean
        statsVisible: boolean
        extensionPercentage: number
        lastDragPosition: null
        heatmapPosition: { x: number; y: number }
        actionsPosition: { x: number; y: number }
        statsPosition: { x: number; y: number }
    }
    reducerOptions: any
    reducers: {
        heatmapInfoVisible: (state: boolean, action: any, fullState: any) => boolean
        actionsInfoVisible: (state: boolean, action: any, fullState: any) => boolean
        statsVisible: (state: boolean, action: any, fullState: any) => boolean
        extensionPercentage: (state: number, action: any, fullState: any) => number
        lastDragPosition: (state: null, action: any, fullState: any) => null
        heatmapPosition: (state: { x: number; y: number }, action: any, fullState: any) => { x: number; y: number }
        actionsPosition: (state: { x: number; y: number }, action: any, fullState: any) => { x: number; y: number }
        statsPosition: (state: { x: number; y: number }, action: any, fullState: any) => { x: number; y: number }
    }
    selector: (
        state: any
    ) => {
        heatmapInfoVisible: boolean
        actionsInfoVisible: boolean
        statsVisible: boolean
        extensionPercentage: number
        lastDragPosition: null
        heatmapPosition: { x: number; y: number }
        actionsPosition: { x: number; y: number }
        statsPosition: { x: number; y: number }
    }
    selectors: {
        heatmapInfoVisible: (state: any, props: any) => boolean
        actionsInfoVisible: (state: any, props: any) => boolean
        statsVisible: (state: any, props: any) => boolean
        extensionPercentage: (state: any, props: any) => number
        lastDragPosition: (state: any, props: any) => null
        heatmapPosition: (state: any, props: any) => { x: number; y: number }
        actionsPosition: (state: any, props: any) => { x: number; y: number }
        statsPosition: (state: any, props: any) => { x: number; y: number }
        dragPosition: (state: any, props: any) => { x: number; y: number }
        toolbarListVerticalPadding: (state: any, props: any) => number
        dockButtonOnTop: (state: any, props: any) => boolean
        side: (state: any, props: any) => 'left' | 'right'
        closeDistance: (state: any, props: any) => number
        closeRotation: (state: any, props: any) => number
        inspectExtensionPercentage: (state: any, props: any) => any
        heatmapExtensionPercentage: (state: any, props: any) => any
        heatmapWindowVisible: (state: any, props: any) => any
        actionsExtensionPercentage: (state: any, props: any) => any
        actionsWindowVisible: (state: any, props: any) => any
        statsExtensionPercentage: (state: any, props: any) => any
    }
    values: {
        heatmapInfoVisible: boolean
        actionsInfoVisible: boolean
        statsVisible: boolean
        extensionPercentage: number
        lastDragPosition: null
        heatmapPosition: { x: number; y: number }
        actionsPosition: { x: number; y: number }
        statsPosition: { x: number; y: number }
        dragPosition: { x: number; y: number }
        toolbarListVerticalPadding: number
        dockButtonOnTop: boolean
        side: 'left' | 'right'
        closeDistance: number
        closeRotation: number
        inspectExtensionPercentage: any
        heatmapExtensionPercentage: any
        heatmapWindowVisible: any
        actionsExtensionPercentage: any
        actionsWindowVisible: any
        statsExtensionPercentage: any
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        dragPosition: (arg1: any, arg2: any, arg3: any) => { x: number; y: number }
        toolbarListVerticalPadding: (arg1: any, arg2: any) => number
        dockButtonOnTop: (arg1: any, arg2: any) => boolean
        side: (arg1: any, arg2: any) => 'left' | 'right'
        closeDistance: (arg1: any, arg2: any) => number
        closeRotation: (arg1: any, arg2: any) => number
        inspectExtensionPercentage: (arg1: any, arg2: any) => any
        heatmapExtensionPercentage: (arg1: any, arg2: any) => any
        heatmapWindowVisible: (arg1: any, arg2: any) => any
        actionsExtensionPercentage: (arg1: any, arg2: any) => any
        actionsWindowVisible: (arg1: any, arg2: any) => any
        statsExtensionPercentage: (arg1: any, arg2: any) => any
    }
}
