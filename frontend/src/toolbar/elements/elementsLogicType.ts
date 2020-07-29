// Auto-generated with kea-typegen. DO NOT EDIT!

export interface elementsLogicType<
    ToolbarTab,
    ToolbarMode,
    ActionStepType,
    ActionForm,
    ActionType,
    ElementWithMetadata,
    ActionElementWithMetadata,
    ActionElementMap,
    ElementMap
> {
    key: any
    actionCreators: {
        enableInspect: () => {
            type: 'enable inspect (toolbar.elements.elementsLogic)'
            payload: {
                value: boolean
            }
        }
        disableInspect: () => {
            type: 'disable inspect (toolbar.elements.elementsLogic)'
            payload: {
                value: boolean
            }
        }
        selectElement: (
            element: HTMLElement | null
        ) => {
            type: 'select element (toolbar.elements.elementsLogic)'
            payload: { element: HTMLElement | null }
        }
        createAction: (
            element: HTMLElement
        ) => {
            type: 'create action (toolbar.elements.elementsLogic)'
            payload: { element: HTMLElement }
        }
        updateRects: () => {
            type: 'update rects (toolbar.elements.elementsLogic)'
            payload: {
                value: boolean
            }
        }
        setHoverElement: (
            element: HTMLElement | null
        ) => {
            type: 'set hover element (toolbar.elements.elementsLogic)'
            payload: { element: HTMLElement | null }
        }
        setHighlightElement: (
            element: HTMLElement | null
        ) => {
            type: 'set highlight element (toolbar.elements.elementsLogic)'
            payload: { element: HTMLElement | null }
        }
        setSelectedElement: (
            element: HTMLElement | null
        ) => {
            type: 'set selected element (toolbar.elements.elementsLogic)'
            payload: { element: HTMLElement | null }
        }
    }
    actionKeys: {
        'enable inspect (toolbar.elements.elementsLogic)': 'enableInspect'
        'disable inspect (toolbar.elements.elementsLogic)': 'disableInspect'
        'select element (toolbar.elements.elementsLogic)': 'selectElement'
        'create action (toolbar.elements.elementsLogic)': 'createAction'
        'update rects (toolbar.elements.elementsLogic)': 'updateRects'
        'set hover element (toolbar.elements.elementsLogic)': 'setHoverElement'
        'set highlight element (toolbar.elements.elementsLogic)': 'setHighlightElement'
        'set selected element (toolbar.elements.elementsLogic)': 'setSelectedElement'
    }
    actionTypes: {
        enableInspect: 'enable inspect (toolbar.elements.elementsLogic)'
        disableInspect: 'disable inspect (toolbar.elements.elementsLogic)'
        selectElement: 'select element (toolbar.elements.elementsLogic)'
        createAction: 'create action (toolbar.elements.elementsLogic)'
        updateRects: 'update rects (toolbar.elements.elementsLogic)'
        setHoverElement: 'set hover element (toolbar.elements.elementsLogic)'
        setHighlightElement: 'set highlight element (toolbar.elements.elementsLogic)'
        setSelectedElement: 'set selected element (toolbar.elements.elementsLogic)'
    }
    actions: {
        enableInspect: () => {
            type: 'enable inspect (toolbar.elements.elementsLogic)'
            payload: {
                value: boolean
            }
        }
        disableInspect: () => {
            type: 'disable inspect (toolbar.elements.elementsLogic)'
            payload: {
                value: boolean
            }
        }
        selectElement: (
            element: HTMLElement | null
        ) => {
            type: 'select element (toolbar.elements.elementsLogic)'
            payload: { element: HTMLElement | null }
        }
        createAction: (
            element: HTMLElement
        ) => {
            type: 'create action (toolbar.elements.elementsLogic)'
            payload: { element: HTMLElement }
        }
        updateRects: () => {
            type: 'update rects (toolbar.elements.elementsLogic)'
            payload: {
                value: boolean
            }
        }
        setHoverElement: (
            element: HTMLElement | null
        ) => {
            type: 'set hover element (toolbar.elements.elementsLogic)'
            payload: { element: HTMLElement | null }
        }
        setHighlightElement: (
            element: HTMLElement | null
        ) => {
            type: 'set highlight element (toolbar.elements.elementsLogic)'
            payload: { element: HTMLElement | null }
        }
        setSelectedElement: (
            element: HTMLElement | null
        ) => {
            type: 'set selected element (toolbar.elements.elementsLogic)'
            payload: { element: HTMLElement | null }
        }
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['toolbar', 'elements', 'elementsLogic']
    pathString: 'toolbar.elements.elementsLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        inspectEnabledRaw: boolean
        rectUpdateCounter: number
        hoverElement: HTMLElement | null
        highlightElement: HTMLElement | null
        selectedElement: HTMLElement | null
        enabledLast: null | 'inspect' | 'heatmap'
    }
    reducerOptions: any
    reducers: {
        inspectEnabledRaw: (state: boolean, action: any, fullState: any) => boolean
        rectUpdateCounter: (state: number, action: any, fullState: any) => number
        hoverElement: (state: HTMLElement | null, action: any, fullState: any) => HTMLElement | null
        highlightElement: (state: HTMLElement | null, action: any, fullState: any) => HTMLElement | null
        selectedElement: (state: HTMLElement | null, action: any, fullState: any) => HTMLElement | null
        enabledLast: (state: null | 'inspect' | 'heatmap', action: any, fullState: any) => null | 'inspect' | 'heatmap'
    }
    selector: (
        state: any
    ) => {
        inspectEnabledRaw: boolean
        rectUpdateCounter: number
        hoverElement: HTMLElement | null
        highlightElement: HTMLElement | null
        selectedElement: HTMLElement | null
        enabledLast: null | 'inspect' | 'heatmap'
    }
    selectors: {
        inspectEnabledRaw: (state: any, props: any) => boolean
        rectUpdateCounter: (state: any, props: any) => number
        hoverElement: (state: any, props: any) => HTMLElement | null
        highlightElement: (state: any, props: any) => HTMLElement | null
        selectedElement: (state: any, props: any) => HTMLElement | null
        enabledLast: (state: any, props: any) => null | 'inspect' | 'heatmap'
        inspectEnabled: (state: any, props: any) => boolean
        heatmapEnabled: (state: any, props: any) => boolean
        heatmapElements: (state: any, props: any) => ElementWithMetadata[]
        allInspectElements: (state: any, props: any) => HTMLElement[]
        inspectElements: (state: any, props: any) => ElementWithMetadata[]
        displayActionElements: (state: any, props: any) => boolean
        allActionElements: (state: any, props: any) => ElementWithMetadata[]
        actionElements: (state: any, props: any) => ElementWithMetadata[]
        elementMap: (state: any, props: any) => ElementMap
        actionsForElementMap: (state: any, props: any) => ActionElementMap
        elementsWithActions: (state: any, props: any) => HTMLElement[]
        actionsListElements: (state: any, props: any) => ActionElementWithMetadata[]
        elementsToDisplayRaw: (state: any, props: any) => ElementWithMetadata[]
        elementsToDisplay: (state: any, props: any) => ElementWithMetadata[]
        labelsToDisplay: (state: any, props: any) => ElementWithMetadata[]
        selectedElementMeta: (
            state: any,
            props: any
        ) => {
            actionStep: ActionStepType
            actions: ActionElementWithMetadata[]
            element: HTMLElement
            rect?: DOMRect | undefined
            index?: number | undefined
        } | null
        hoverElementMeta: (
            state: any,
            props: any
        ) => {
            actionStep: ActionStepType
            actions: ActionElementWithMetadata[]
            element: HTMLElement
            rect?: DOMRect | undefined
            index?: number | undefined
        } | null
        highlightElementMeta: (
            state: any,
            props: any
        ) => {
            actionStep: ActionStepType
            actions: ActionElementWithMetadata[]
            element: HTMLElement
            rect?: DOMRect | undefined
            index?: number | undefined
        } | null
    }
    values: {
        inspectEnabledRaw: boolean
        rectUpdateCounter: number
        hoverElement: HTMLElement | null
        highlightElement: HTMLElement | null
        selectedElement: HTMLElement | null
        enabledLast: null | 'inspect' | 'heatmap'
        inspectEnabled: boolean
        heatmapEnabled: boolean
        heatmapElements: ElementWithMetadata[]
        allInspectElements: HTMLElement[]
        inspectElements: ElementWithMetadata[]
        displayActionElements: boolean
        allActionElements: ElementWithMetadata[]
        actionElements: ElementWithMetadata[]
        elementMap: ElementMap
        actionsForElementMap: ActionElementMap
        elementsWithActions: HTMLElement[]
        actionsListElements: ActionElementWithMetadata[]
        elementsToDisplayRaw: ElementWithMetadata[]
        elementsToDisplay: ElementWithMetadata[]
        labelsToDisplay: ElementWithMetadata[]
        selectedElementMeta: {
            actionStep: ActionStepType
            actions: ActionElementWithMetadata[]
            element: HTMLElement
            rect?: DOMRect | undefined
            index?: number | undefined
        } | null
        hoverElementMeta: {
            actionStep: ActionStepType
            actions: ActionElementWithMetadata[]
            element: HTMLElement
            rect?: DOMRect | undefined
            index?: number | undefined
        } | null
        highlightElementMeta: {
            actionStep: ActionStepType
            actions: ActionElementWithMetadata[]
            element: HTMLElement
            rect?: DOMRect | undefined
            index?: number | undefined
        } | null
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        inspectEnabled: (
            arg1: ToolbarMode,
            arg2: boolean,
            arg3: ToolbarTab,
            arg4: number | null,
            arg5: boolean
        ) => boolean
        heatmapEnabled: (arg1: boolean, arg2: ToolbarTab) => boolean
        heatmapElements: (
            arg1: {
                position: number
                count: number
                element: HTMLElement
                hash: string
                selector: string
                actionStep?: ActionStepType | undefined
            }[],
            arg2: number,
            arg3: boolean
        ) => ElementWithMetadata[]
        allInspectElements: (arg1: boolean) => HTMLElement[]
        inspectElements: (arg1: HTMLElement[], arg2: number, arg3: boolean) => ElementWithMetadata[]
        displayActionElements: (arg1: ToolbarMode, arg2: ToolbarTab, arg3: boolean) => boolean
        allActionElements: (arg1: boolean, arg2: ActionForm) => ElementWithMetadata[]
        actionElements: (arg1: ElementWithMetadata[], arg2: number, arg3: boolean) => ElementWithMetadata[]
        elementMap: (
            arg1: ElementWithMetadata[],
            arg2: ElementWithMetadata[],
            arg3: ElementWithMetadata[],
            arg4: ActionElementWithMetadata[]
        ) => ElementMap
        actionsForElementMap: (arg1: ActionType[], arg2: number, arg3: boolean) => ActionElementMap
        elementsWithActions: (arg1: ActionElementMap) => HTMLElement[]
        actionsListElements: (arg1: ActionElementMap) => ActionElementWithMetadata[]
        elementsToDisplayRaw: (
            arg1: boolean,
            arg2: ElementWithMetadata[],
            arg3: ElementWithMetadata[],
            arg4: ActionElementWithMetadata[],
            arg5: ActionType | null
        ) => ElementWithMetadata[]
        elementsToDisplay: (arg1: ElementWithMetadata[]) => ElementWithMetadata[]
        labelsToDisplay: (
            arg1: boolean,
            arg2: ElementWithMetadata[],
            arg3: ActionElementWithMetadata[],
            arg4: ActionType | null
        ) => ElementWithMetadata[]
        selectedElementMeta: (
            arg1: HTMLElement | null,
            arg2: ElementMap,
            arg3: ActionElementMap
        ) => {
            actionStep: ActionStepType
            actions: ActionElementWithMetadata[]
            element: HTMLElement
            rect?: DOMRect | undefined
            index?: number | undefined
        } | null
        hoverElementMeta: (
            arg1: HTMLElement | null,
            arg2: ElementMap,
            arg3: ActionElementMap
        ) => {
            actionStep: ActionStepType
            actions: ActionElementWithMetadata[]
            element: HTMLElement
            rect?: DOMRect | undefined
            index?: number | undefined
        } | null
        highlightElementMeta: (
            arg1: HTMLElement | null,
            arg2: ElementMap,
            arg3: ActionElementMap
        ) => {
            actionStep: ActionStepType
            actions: ActionElementWithMetadata[]
            element: HTMLElement
            rect?: DOMRect | undefined
            index?: number | undefined
        } | null
    }
    __keaTypeGenInternalReducerActions: {
        'set tab (toolbar.toolbarTabLogic)': (
            tab: ToolbarTab
        ) => {
            type: 'set tab (toolbar.toolbarTabLogic)'
            payload: {
                tab: ToolbarTab
            }
        }
        'disable heatmap (toolbar.elements.heatmapLogic)': () => {
            type: 'disable heatmap (toolbar.elements.heatmapLogic)'
            payload: {
                value: boolean
            }
        }
        'select action (toolbar.actions.actionsTabLogic)': (
            id: number | null
        ) => {
            type: 'select action (toolbar.actions.actionsTabLogic)'
            payload: {
                id: number | null
            }
        }
        'enable heatmap (toolbar.elements.heatmapLogic)': () => {
            type: 'enable heatmap (toolbar.elements.heatmapLogic)'
            payload: {
                value: boolean
            }
        }
    }
}
