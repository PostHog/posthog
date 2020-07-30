// Auto-generated with kea-typegen. DO NOT EDIT!

export interface heatmapLogicType<ElementsEventType, CountedHTMLElement, ActionStepType> {
    key: any
    actionCreators: {
        enableHeatmap: () => {
            type: 'enable heatmap (frontend.src.toolbar.elements.heatmapLogic)'
            payload: {
                value: boolean
            }
        }
        disableHeatmap: () => {
            type: 'disable heatmap (frontend.src.toolbar.elements.heatmapLogic)'
            payload: {
                value: boolean
            }
        }
        setShowHeatmapTooltip: (
            showHeatmapTooltip: boolean
        ) => {
            type: 'set show heatmap tooltip (frontend.src.toolbar.elements.heatmapLogic)'
            payload: { showHeatmapTooltip: boolean }
        }
        resetEvents: () => {
            type: 'reset events (frontend.src.toolbar.elements.heatmapLogic)'
            payload: any
        }
        resetEventsSuccess: (
            events: ElementsEventType[]
        ) => {
            type: 'reset events success (frontend.src.toolbar.elements.heatmapLogic)'
            payload: {
                events: ElementsEventType[]
            }
        }
        resetEventsFailure: (
            error: string
        ) => {
            type: 'reset events failure (frontend.src.toolbar.elements.heatmapLogic)'
            payload: {
                error: string
            }
        }
        getEvents: ({
            $current_url,
        }: {
            $current_url: string
        }) => {
            type: 'get events (frontend.src.toolbar.elements.heatmapLogic)'
            payload: {
                $current_url: string
            }
        }
        getEventsSuccess: (
            events: ElementsEventType[]
        ) => {
            type: 'get events success (frontend.src.toolbar.elements.heatmapLogic)'
            payload: {
                events: ElementsEventType[]
            }
        }
        getEventsFailure: (
            error: string
        ) => {
            type: 'get events failure (frontend.src.toolbar.elements.heatmapLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'enable heatmap (frontend.src.toolbar.elements.heatmapLogic)': 'enableHeatmap'
        'disable heatmap (frontend.src.toolbar.elements.heatmapLogic)': 'disableHeatmap'
        'set show heatmap tooltip (frontend.src.toolbar.elements.heatmapLogic)': 'setShowHeatmapTooltip'
        'reset events (frontend.src.toolbar.elements.heatmapLogic)': 'resetEvents'
        'reset events success (frontend.src.toolbar.elements.heatmapLogic)': 'resetEventsSuccess'
        'reset events failure (frontend.src.toolbar.elements.heatmapLogic)': 'resetEventsFailure'
        'get events (frontend.src.toolbar.elements.heatmapLogic)': 'getEvents'
        'get events success (frontend.src.toolbar.elements.heatmapLogic)': 'getEventsSuccess'
        'get events failure (frontend.src.toolbar.elements.heatmapLogic)': 'getEventsFailure'
    }
    actionTypes: {
        enableHeatmap: 'enable heatmap (frontend.src.toolbar.elements.heatmapLogic)'
        disableHeatmap: 'disable heatmap (frontend.src.toolbar.elements.heatmapLogic)'
        setShowHeatmapTooltip: 'set show heatmap tooltip (frontend.src.toolbar.elements.heatmapLogic)'
        resetEvents: 'reset events (frontend.src.toolbar.elements.heatmapLogic)'
        resetEventsSuccess: 'reset events success (frontend.src.toolbar.elements.heatmapLogic)'
        resetEventsFailure: 'reset events failure (frontend.src.toolbar.elements.heatmapLogic)'
        getEvents: 'get events (frontend.src.toolbar.elements.heatmapLogic)'
        getEventsSuccess: 'get events success (frontend.src.toolbar.elements.heatmapLogic)'
        getEventsFailure: 'get events failure (frontend.src.toolbar.elements.heatmapLogic)'
    }
    actions: {
        enableHeatmap: () => void
        disableHeatmap: () => void
        setShowHeatmapTooltip: (showHeatmapTooltip: boolean) => void
        resetEvents: () => void
        resetEventsSuccess: (events: ElementsEventType[]) => void
        resetEventsFailure: (error: string) => void
        getEvents: ({ $current_url }: { $current_url: string }) => void
        getEventsSuccess: (events: ElementsEventType[]) => void
        getEventsFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'toolbar', 'elements', 'heatmapLogic']
    pathString: 'frontend.src.toolbar.elements.heatmapLogic'
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
        events: ElementsEventType[]
        eventsLoading: boolean
    }
    reducerOptions: any
    reducers: {
        heatmapEnabled: (state: boolean, action: any, fullState: any) => boolean
        heatmapLoading: (state: boolean, action: any, fullState: any) => boolean
        showHeatmapTooltip: (state: boolean, action: any, fullState: any) => boolean
        events: (state: ElementsEventType[], action: any, fullState: any) => ElementsEventType[]
        eventsLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        heatmapEnabled: boolean
        heatmapLoading: boolean
        showHeatmapTooltip: boolean
        events: ElementsEventType[]
        eventsLoading: boolean
    }
    selectors: {
        heatmapEnabled: (state: any, props: any) => boolean
        heatmapLoading: (state: any, props: any) => boolean
        showHeatmapTooltip: (state: any, props: any) => boolean
        events: (state: any, props: any) => ElementsEventType[]
        eventsLoading: (state: any, props: any) => boolean
        elements: (state: any, props: any) => CountedHTMLElement[]
        countedElements: (
            state: any,
            props: any
        ) => {
            position: number
            count: number
            element: HTMLElement
            hash: string
            selector: string
            actionStep?: ActionStepType | undefined
        }[]
        elementCount: (state: any, props: any) => number
        clickCount: (state: any, props: any) => number
        highestClickCount: (state: any, props: any) => number
    }
    values: {
        heatmapEnabled: boolean
        heatmapLoading: boolean
        showHeatmapTooltip: boolean
        events: ElementsEventType[]
        eventsLoading: boolean
        elements: CountedHTMLElement[]
        countedElements: {
            position: number
            count: number
            element: HTMLElement
            hash: string
            selector: string
            actionStep?: ActionStepType | undefined
        }[]
        elementCount: number
        clickCount: number
        highestClickCount: number
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        elements: (arg1: ElementsEventType[]) => CountedHTMLElement[]
        countedElements: (
            arg1: CountedHTMLElement[]
        ) => {
            position: number
            count: number
            element: HTMLElement
            hash: string
            selector: string
            actionStep?: ActionStepType | undefined
        }[]
        elementCount: (
            arg1: {
                position: number
                count: number
                element: HTMLElement
                hash: string
                selector: string
                actionStep?: ActionStepType | undefined
            }[]
        ) => number
        clickCount: (
            arg1: {
                position: number
                count: number
                element: HTMLElement
                hash: string
                selector: string
                actionStep?: ActionStepType | undefined
            }[]
        ) => number
        highestClickCount: (
            arg1: {
                position: number
                count: number
                element: HTMLElement
                hash: string
                selector: string
                actionStep?: ActionStepType | undefined
            }[]
        ) => number
    }
}
