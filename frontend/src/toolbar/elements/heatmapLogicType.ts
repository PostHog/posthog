// Auto-generated with kea-typegen. DO NOT EDIT!

export interface heatmapLogicType {
    key: any
    actionCreators: {
        enableHeatmap: () => {
            type: 'enable heatmap (toolbar.elements.heatmapLogic)'
            payload: {
                value: boolean
            }
        }
        disableHeatmap: () => {
            type: 'disable heatmap (toolbar.elements.heatmapLogic)'
            payload: {
                value: boolean
            }
        }
        setShowHeatmapTooltip: (
            showHeatmapTooltip: any
        ) => {
            type: 'set show heatmap tooltip (toolbar.elements.heatmapLogic)'
            payload: { showHeatmapTooltip: any }
        }
        resetEvents: () => {
            type: 'reset events (toolbar.elements.heatmapLogic)'
            payload: any
        }
        resetEventsSuccess: (
            events: never[]
        ) => {
            type: 'reset events success (toolbar.elements.heatmapLogic)'
            payload: {
                events: never[]
            }
        }
        resetEventsFailure: (
            error: string
        ) => {
            type: 'reset events failure (toolbar.elements.heatmapLogic)'
            payload: {
                error: string
            }
        }
        getEvents: ({
            $current_url,
        }: any) => {
            type: 'get events (toolbar.elements.heatmapLogic)'
            payload: any
        }
        getEventsSuccess: (
            events: never[]
        ) => {
            type: 'get events success (toolbar.elements.heatmapLogic)'
            payload: {
                events: never[]
            }
        }
        getEventsFailure: (
            error: string
        ) => {
            type: 'get events failure (toolbar.elements.heatmapLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'enable heatmap (toolbar.elements.heatmapLogic)': 'enableHeatmap'
        'disable heatmap (toolbar.elements.heatmapLogic)': 'disableHeatmap'
        'set show heatmap tooltip (toolbar.elements.heatmapLogic)': 'setShowHeatmapTooltip'
        'reset events (toolbar.elements.heatmapLogic)': 'resetEvents'
        'reset events success (toolbar.elements.heatmapLogic)': 'resetEventsSuccess'
        'reset events failure (toolbar.elements.heatmapLogic)': 'resetEventsFailure'
        'get events (toolbar.elements.heatmapLogic)': 'getEvents'
        'get events success (toolbar.elements.heatmapLogic)': 'getEventsSuccess'
        'get events failure (toolbar.elements.heatmapLogic)': 'getEventsFailure'
    }
    actionTypes: {
        enableHeatmap: 'enable heatmap (toolbar.elements.heatmapLogic)'
        disableHeatmap: 'disable heatmap (toolbar.elements.heatmapLogic)'
        setShowHeatmapTooltip: 'set show heatmap tooltip (toolbar.elements.heatmapLogic)'
        resetEvents: 'reset events (toolbar.elements.heatmapLogic)'
        resetEventsSuccess: 'reset events success (toolbar.elements.heatmapLogic)'
        resetEventsFailure: 'reset events failure (toolbar.elements.heatmapLogic)'
        getEvents: 'get events (toolbar.elements.heatmapLogic)'
        getEventsSuccess: 'get events success (toolbar.elements.heatmapLogic)'
        getEventsFailure: 'get events failure (toolbar.elements.heatmapLogic)'
    }
    actions: {
        enableHeatmap: () => {
            type: 'enable heatmap (toolbar.elements.heatmapLogic)'
            payload: {
                value: boolean
            }
        }
        disableHeatmap: () => {
            type: 'disable heatmap (toolbar.elements.heatmapLogic)'
            payload: {
                value: boolean
            }
        }
        setShowHeatmapTooltip: (
            showHeatmapTooltip: any
        ) => {
            type: 'set show heatmap tooltip (toolbar.elements.heatmapLogic)'
            payload: { showHeatmapTooltip: any }
        }
        resetEvents: () => {
            type: 'reset events (toolbar.elements.heatmapLogic)'
            payload: any
        }
        resetEventsSuccess: (
            events: never[]
        ) => {
            type: 'reset events success (toolbar.elements.heatmapLogic)'
            payload: {
                events: never[]
            }
        }
        resetEventsFailure: (
            error: string
        ) => {
            type: 'reset events failure (toolbar.elements.heatmapLogic)'
            payload: {
                error: string
            }
        }
        getEvents: ({
            $current_url,
        }: any) => {
            type: 'get events (toolbar.elements.heatmapLogic)'
            payload: any
        }
        getEventsSuccess: (
            events: never[]
        ) => {
            type: 'get events success (toolbar.elements.heatmapLogic)'
            payload: {
                events: never[]
            }
        }
        getEventsFailure: (
            error: string
        ) => {
            type: 'get events failure (toolbar.elements.heatmapLogic)'
            payload: {
                error: string
            }
        }
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['toolbar', 'elements', 'heatmapLogic']
    pathString: 'toolbar.elements.heatmapLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        heatmapEnabled: boolean
        heatmapLoading: boolean
        showHeatmapTooltip: boolean
        events: never[]
        eventsLoading: boolean
    }
    reducerOptions: any
    reducers: {
        heatmapEnabled: (state: boolean, action: any, fullState: any) => boolean
        heatmapLoading: (state: boolean, action: any, fullState: any) => boolean
        showHeatmapTooltip: (state: boolean, action: any, fullState: any) => boolean
        events: (state: never[], action: any, fullState: any) => never[]
        eventsLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        heatmapEnabled: boolean
        heatmapLoading: boolean
        showHeatmapTooltip: boolean
        events: never[]
        eventsLoading: boolean
    }
    selectors: {
        heatmapEnabled: (state: any, props: any) => boolean
        heatmapLoading: (state: any, props: any) => boolean
        showHeatmapTooltip: (state: any, props: any) => boolean
        events: (state: any, props: any) => never[]
        eventsLoading: (state: any, props: any) => boolean
        elements: (state: any, props: any) => any
        countedElements: (state: any, props: any) => any[]
        elementCount: (state: any, props: any) => any
        clickCount: (state: any, props: any) => any
        highestClickCount: (state: any, props: any) => any
    }
    values: {
        heatmapEnabled: boolean
        heatmapLoading: boolean
        showHeatmapTooltip: boolean
        events: never[]
        eventsLoading: boolean
        elements: any
        countedElements: any[]
        elementCount: any
        clickCount: any
        highestClickCount: any
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        elements: (arg1: any) => any
        countedElements: (arg1: any) => any[]
        elementCount: (arg1: any) => any
        clickCount: (arg1: any) => any
        highestClickCount: (arg1: any) => any
    }
}
