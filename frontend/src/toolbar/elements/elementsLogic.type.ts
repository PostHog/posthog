// Auto-generated with kea-typegen. DO NOT EDIT!

export interface elementsLogicType<ToolbarMode> {
    key: any;
    actionCreators: {
        enableInspect: () => ({
            type: "enable inspect (frontend.src.toolbar.elements.elementsLogic)";
            payload: {
                value: boolean;
            };
        });
        disableInspect: () => ({
            type: "disable inspect (frontend.src.toolbar.elements.elementsLogic)";
            payload: {
                value: boolean;
            };
        });
        selectElement: (element: any) => ({
            type: "select element (frontend.src.toolbar.elements.elementsLogic)";
            payload: { element: any; };
        });
        createAction: (element: any) => ({
            type: "create action (frontend.src.toolbar.elements.elementsLogic)";
            payload: { element: any; };
        });
        updateRects: () => ({
            type: "update rects (frontend.src.toolbar.elements.elementsLogic)";
            payload: {
                value: boolean;
            };
        });
        setHoverElement: (element: any) => ({
            type: "set hover element (frontend.src.toolbar.elements.elementsLogic)";
            payload: { element: any; };
        });
        setHighlightElement: (element: any) => ({
            type: "set highlight element (frontend.src.toolbar.elements.elementsLogic)";
            payload: { element: any; };
        });
        setSelectedElement: (element: any) => ({
            type: "set selected element (frontend.src.toolbar.elements.elementsLogic)";
            payload: { element: any; };
        });
    };
    actionKeys: any;
    actions: {
        enableInspect: () => ({
            type: "enable inspect (frontend.src.toolbar.elements.elementsLogic)";
            payload: {
                value: boolean;
            };
        });
        disableInspect: () => ({
            type: "disable inspect (frontend.src.toolbar.elements.elementsLogic)";
            payload: {
                value: boolean;
            };
        });
        selectElement: (element: any) => ({
            type: "select element (frontend.src.toolbar.elements.elementsLogic)";
            payload: { element: any; };
        });
        createAction: (element: any) => ({
            type: "create action (frontend.src.toolbar.elements.elementsLogic)";
            payload: { element: any; };
        });
        updateRects: () => ({
            type: "update rects (frontend.src.toolbar.elements.elementsLogic)";
            payload: {
                value: boolean;
            };
        });
        setHoverElement: (element: any) => ({
            type: "set hover element (frontend.src.toolbar.elements.elementsLogic)";
            payload: { element: any; };
        });
        setHighlightElement: (element: any) => ({
            type: "set highlight element (frontend.src.toolbar.elements.elementsLogic)";
            payload: { element: any; };
        });
        setSelectedElement: (element: any) => ({
            type: "set selected element (frontend.src.toolbar.elements.elementsLogic)";
            payload: { element: any; };
        });
    };
    cache: Record<string, any>;
    connections: any;
    constants: any;
    defaults: any;
    events: any;
    path: ["frontend", "src", "toolbar", "elements", "elementsLogic"];
    pathString: "frontend.src.toolbar.elements.elementsLogic";
    propTypes: any;
    props: Record<string, any>;
    reducer: (state: any, action: () => any, fullState: any) => {
        inspectEnabledRaw: boolean;
        rectUpdateCounter: number;
        hoverElement: any;
        highlightElement: any;
        selectedElement: any;
        enabledLast: any;
    };
    reducerOptions: any;
    reducers: {
        inspectEnabledRaw: (state: boolean, action: any, fullState: any) => boolean;
        rectUpdateCounter: (state: number, action: any, fullState: any) => number;
        hoverElement: (state: any, action: any, fullState: any) => any;
        highlightElement: (state: any, action: any, fullState: any) => any;
        selectedElement: (state: any, action: any, fullState: any) => any;
        enabledLast: (state: any, action: any, fullState: any) => any;
    };
    selector: (state: any) => {
        inspectEnabledRaw: boolean;
        rectUpdateCounter: number;
        hoverElement: any;
        highlightElement: any;
        selectedElement: any;
        enabledLast: any;
    };
    selectors: {
        inspectEnabledRaw: (state: any, props: any) => boolean;
        rectUpdateCounter: (state: any, props: any) => number;
        hoverElement: (state: any, props: any) => any;
        highlightElement: (state: any, props: any) => any;
        selectedElement: (state: any, props: any) => any;
        enabledLast: (state: any, props: any) => any;
        inspectEnabled: (state: any, props: any) => boolean;
        heatmapEnabled: (state: any, props: any) => boolean;
        heatmapElements: (state: any, props: any) => any[];
        allInspectElements: (state: any, props: any) => any;
        inspectElements: (state: any, props: any) => any;
        displayActionElements: (state: any, props: any) => any;
        allActionElements: (state: any, props: any) => any;
        actionElements: (state: any, props: any) => any;
        elementMap: (state: any, props: any) => Map<any, any>;
        actionsForElementMap: (state: any, props: any) => Map<any, any>;
        elementsWithActions: (state: any, props: any) => any[];
        actionsListElements: (state: any, props: any) => any[];
        elementsToDisplayRaw: (state: any, props: any) => any;
        elementsToDisplay: (state: any, props: any) => any;
        labelsToDisplay: (state: any, props: any) => any;
        actionLabelsToDisplay: (state: any, props: any) => any[];
        selectedElementMeta: (state: any, props: any) => any;
        hoverElementMeta: (state: any, props: any) => any;
        highlightElementMeta: (state: any, props: any) => any;
    };
    values: {
        inspectEnabledRaw: boolean;
        rectUpdateCounter: number;
        hoverElement: any;
        highlightElement: any;
        selectedElement: any;
        enabledLast: any;
        inspectEnabled: boolean;
        heatmapEnabled: boolean;
        heatmapElements: any[];
        allInspectElements: any;
        inspectElements: any;
        displayActionElements: any;
        allActionElements: any;
        actionElements: any;
        elementMap: Map<any, any>;
        actionsForElementMap: Map<any, any>;
        elementsWithActions: any[];
        actionsListElements: any[];
        elementsToDisplayRaw: any;
        elementsToDisplay: any;
        labelsToDisplay: any;
        actionLabelsToDisplay: any[];
        selectedElementMeta: any;
        hoverElementMeta: any;
        highlightElementMeta: any;
    };
    _isKea: true;
    __selectorTypeHelp: {
        inspectEnabled: (arg1: ToolbarMode, arg2: boolean, arg3: string, arg4: any, arg5: any) => boolean;
        heatmapEnabled: (arg1: boolean, arg2: string) => boolean;
        heatmapElements: (arg1: any[], arg2: number, arg3: boolean) => any[];
        allInspectElements: (arg1: boolean) => any;
        inspectElements: (arg1: any, arg2: number, arg3: boolean) => any;
        displayActionElements: (arg1: ToolbarMode, arg2: string, arg3: any) => any;
        allActionElements: (arg1: any, arg2: any) => any;
        actionElements: (arg1: any, arg2: number, arg3: boolean) => any;
        elementMap: (arg1: any[], arg2: any, arg3: any, arg4: any[]) => Map<any, any>;
        actionsForElementMap: (arg1: any, arg2: number, arg3: boolean) => Map<any, any>;
        elementsWithActions: (arg1: Map<any, any>) => any[];
        actionsListElements: (arg1: Map<any, any>) => any[];
        elementsToDisplayRaw: (arg1: any, arg2: any, arg3: any, arg4: any[], arg5: any) => any;
        elementsToDisplay: (arg1: any) => any;
        labelsToDisplay: (arg1: any, arg2: any, arg3: any[], arg4: any) => any;
        actionLabelsToDisplay: (arg1: any[], arg2: boolean, arg3: any) => any[];
        selectedElementMeta: (arg1: any, arg2: Map<any, any>, arg3: Map<any, any>) => any;
        hoverElementMeta: (arg1: any, arg2: Map<any, any>, arg3: Map<any, any>) => any;
        highlightElementMeta: (arg1: any, arg2: Map<any, any>, arg3: Map<any, any>) => any;
    };
}