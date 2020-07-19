// Auto-generated with kea-typegen. DO NOT EDIT!

export interface heatmapLogicType {
    key: any;
    actionCreators: {
        enableHeatmap: () => ({
            type: "enable heatmap (frontend.src.toolbar.elements.heatmapLogic)";
            payload: {
                value: boolean;
            };
        });
        disableHeatmap: () => ({
            type: "disable heatmap (frontend.src.toolbar.elements.heatmapLogic)";
            payload: {
                value: boolean;
            };
        });
        resetEvents: () => ({
            type: "reset events (frontend.src.toolbar.elements.heatmapLogic)";
            payload: any;
        });
        resetEventsSuccess: (events: undefined[]) => ({
            type: "reset events success (frontend.src.toolbar.elements.heatmapLogic)";
            payload: {
                events: undefined[];
            };
        });
        resetEventsFailure: (error: string) => ({
            type: "reset events failure (frontend.src.toolbar.elements.heatmapLogic)";
            payload: {
                error: string;
            };
        });
        getEvents: ({ $current_url }: any) => ({
            type: "get events (frontend.src.toolbar.elements.heatmapLogic)";
            payload: any;
        });
        getEventsSuccess: (events: undefined[]) => ({
            type: "get events success (frontend.src.toolbar.elements.heatmapLogic)";
            payload: {
                events: undefined[];
            };
        });
        getEventsFailure: (error: string) => ({
            type: "get events failure (frontend.src.toolbar.elements.heatmapLogic)";
            payload: {
                error: string;
            };
        });
    };
    actionKeys: any;
    actions: {
        enableHeatmap: () => ({
            type: "enable heatmap (frontend.src.toolbar.elements.heatmapLogic)";
            payload: {
                value: boolean;
            };
        });
        disableHeatmap: () => ({
            type: "disable heatmap (frontend.src.toolbar.elements.heatmapLogic)";
            payload: {
                value: boolean;
            };
        });
        resetEvents: () => ({
            type: "reset events (frontend.src.toolbar.elements.heatmapLogic)";
            payload: any;
        });
        resetEventsSuccess: (events: undefined[]) => ({
            type: "reset events success (frontend.src.toolbar.elements.heatmapLogic)";
            payload: {
                events: undefined[];
            };
        });
        resetEventsFailure: (error: string) => ({
            type: "reset events failure (frontend.src.toolbar.elements.heatmapLogic)";
            payload: {
                error: string;
            };
        });
        getEvents: ({ $current_url }: any) => ({
            type: "get events (frontend.src.toolbar.elements.heatmapLogic)";
            payload: any;
        });
        getEventsSuccess: (events: undefined[]) => ({
            type: "get events success (frontend.src.toolbar.elements.heatmapLogic)";
            payload: {
                events: undefined[];
            };
        });
        getEventsFailure: (error: string) => ({
            type: "get events failure (frontend.src.toolbar.elements.heatmapLogic)";
            payload: {
                error: string;
            };
        });
    };
    cache: Record<string, any>;
    connections: any;
    constants: any;
    defaults: any;
    events: any;
    path: ["frontend", "src", "toolbar", "elements", "heatmapLogic"];
    pathString: "frontend.src.toolbar.elements.heatmapLogic";
    propTypes: any;
    props: Record<string, any>;
    reducer: (state: any, action: () => any, fullState: any) => {
        heatmapEnabled: boolean;
        heatmapLoading: boolean;
        events: undefined[];
        eventsLoading: boolean;
    };
    reducerOptions: any;
    reducers: {
        heatmapEnabled: (state: boolean, action: any, fullState: any) => boolean;
        heatmapLoading: (state: boolean, action: any, fullState: any) => boolean;
        events: (state: undefined[], action: any, fullState: any) => undefined[];
        eventsLoading: (state: boolean, action: any, fullState: any) => boolean;
    };
    selector: (state: any) => {
        heatmapEnabled: boolean;
        heatmapLoading: boolean;
        events: undefined[];
        eventsLoading: boolean;
    };
    selectors: {
        heatmapEnabled: (state: any, props: any) => boolean;
        heatmapLoading: (state: any, props: any) => boolean;
        events: (state: any, props: any) => undefined[];
        eventsLoading: (state: any, props: any) => boolean;
        elements: (state: any, props: any) => { element: any; count: any; selector: any; hash: any; }[];
        countedElements: (state: any, props: any) => any[];
        elementCount: (state: any, props: any) => number;
        clickCount: (state: any, props: any) => any;
        highestClickCount: (state: any, props: any) => any;
    };
    values: {
        heatmapEnabled: boolean;
        heatmapLoading: boolean;
        events: undefined[];
        eventsLoading: boolean;
        elements: { element: any; count: any; selector: any; hash: any; }[];
        countedElements: any[];
        elementCount: number;
        clickCount: any;
        highestClickCount: any;
    };
    _isKea: true;
    __selectorTypeHelp: {
        elements: (arg1: undefined[]) => { element: any; count: any; selector: any; hash: any; }[];
        countedElements: (arg1: { element: any; count: any; selector: any; hash: any; }[]) => any[];
        elementCount: (arg1: any[]) => number;
        clickCount: (arg1: any[]) => any;
        highestClickCount: (arg1: any[]) => any;
    };
}