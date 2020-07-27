// Auto-generated with kea-typegen. DO NOT EDIT!

export interface heatmapLogicType {
    key: any;
    actionCreators: {
        enableHeatmap: () => ({
            type: "enable heatmap (toolbar.elements.heatmapLogic)";
            payload: {
                value: boolean;
            };
        });
        disableHeatmap: () => ({
            type: "disable heatmap (toolbar.elements.heatmapLogic)";
            payload: {
                value: boolean;
            };
        });
        resetEvents: () => ({
            type: "reset events (toolbar.elements.heatmapLogic)";
            payload: any;
        });
        resetEventsSuccess: (events: undefined[]) => ({
            type: "reset events success (toolbar.elements.heatmapLogic)";
            payload: {
                events: undefined[];
            };
        });
        resetEventsFailure: (error: string) => ({
            type: "reset events failure (toolbar.elements.heatmapLogic)";
            payload: {
                error: string;
            };
        });
        getEvents: ({ $current_url }: any) => ({
            type: "get events (toolbar.elements.heatmapLogic)";
            payload: any;
        });
        getEventsSuccess: (events: undefined[]) => ({
            type: "get events success (toolbar.elements.heatmapLogic)";
            payload: {
                events: undefined[];
            };
        });
        getEventsFailure: (error: string) => ({
            type: "get events failure (toolbar.elements.heatmapLogic)";
            payload: {
                error: string;
            };
        });
    };
    actionKeys: {
        "enable heatmap (toolbar.elements.heatmapLogic)": "enableHeatmap";
        "disable heatmap (toolbar.elements.heatmapLogic)": "disableHeatmap";
        "reset events (toolbar.elements.heatmapLogic)": "resetEvents";
        "reset events success (toolbar.elements.heatmapLogic)": "resetEventsSuccess";
        "reset events failure (toolbar.elements.heatmapLogic)": "resetEventsFailure";
        "get events (toolbar.elements.heatmapLogic)": "getEvents";
        "get events success (toolbar.elements.heatmapLogic)": "getEventsSuccess";
        "get events failure (toolbar.elements.heatmapLogic)": "getEventsFailure";
    };
    actionTypes: {
        enableHeatmap: "enable heatmap (toolbar.elements.heatmapLogic)";
        disableHeatmap: "disable heatmap (toolbar.elements.heatmapLogic)";
        resetEvents: "reset events (toolbar.elements.heatmapLogic)";
        resetEventsSuccess: "reset events success (toolbar.elements.heatmapLogic)";
        resetEventsFailure: "reset events failure (toolbar.elements.heatmapLogic)";
        getEvents: "get events (toolbar.elements.heatmapLogic)";
        getEventsSuccess: "get events success (toolbar.elements.heatmapLogic)";
        getEventsFailure: "get events failure (toolbar.elements.heatmapLogic)";
    };
    actions: {
        enableHeatmap: () => ({
            type: "enable heatmap (toolbar.elements.heatmapLogic)";
            payload: {
                value: boolean;
            };
        });
        disableHeatmap: () => ({
            type: "disable heatmap (toolbar.elements.heatmapLogic)";
            payload: {
                value: boolean;
            };
        });
        resetEvents: () => ({
            type: "reset events (toolbar.elements.heatmapLogic)";
            payload: any;
        });
        resetEventsSuccess: (events: undefined[]) => ({
            type: "reset events success (toolbar.elements.heatmapLogic)";
            payload: {
                events: undefined[];
            };
        });
        resetEventsFailure: (error: string) => ({
            type: "reset events failure (toolbar.elements.heatmapLogic)";
            payload: {
                error: string;
            };
        });
        getEvents: ({ $current_url }: any) => ({
            type: "get events (toolbar.elements.heatmapLogic)";
            payload: any;
        });
        getEventsSuccess: (events: undefined[]) => ({
            type: "get events success (toolbar.elements.heatmapLogic)";
            payload: {
                events: undefined[];
            };
        });
        getEventsFailure: (error: string) => ({
            type: "get events failure (toolbar.elements.heatmapLogic)";
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
    path: ["toolbar", "elements", "heatmapLogic"];
    pathString: "toolbar.elements.heatmapLogic";
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
    __keaTypeGenInternalSelectorTypes: {
        elements: (arg1: undefined[]) => { element: any; count: any; selector: any; hash: any; }[];
        countedElements: (arg1: { element: any; count: any; selector: any; hash: any; }[]) => any[];
        elementCount: (arg1: any[]) => number;
        clickCount: (arg1: any[]) => any;
        highestClickCount: (arg1: any[]) => any;
    };
}