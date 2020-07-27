// Auto-generated with kea-typegen. DO NOT EDIT!

export interface toolbarTabLogicType {
    key: any;
    actionCreators: {
        setTab: (tab: string) => ({
            type: "set tab (toolbar.toolbarTabLogic)";
            payload: { tab: string; };
        });
    };
    actionKeys: {
        "set tab (toolbar.toolbarTabLogic)": "setTab";
    };
    actionTypes: {
        setTab: "set tab (toolbar.toolbarTabLogic)";
    };
    actions: {
        setTab: (tab: string) => ({
            type: "set tab (toolbar.toolbarTabLogic)";
            payload: { tab: string; };
        });
    };
    cache: Record<string, any>;
    connections: any;
    constants: any;
    defaults: any;
    events: any;
    path: ["toolbar", "toolbarTabLogic"];
    pathString: "toolbar.toolbarTabLogic";
    propTypes: any;
    props: Record<string, any>;
    reducer: (state: any, action: () => any, fullState: any) => {
        tab: string;
    };
    reducerOptions: any;
    reducers: {
        tab: (state: string, action: any, fullState: any) => string;
    };
    selector: (state: any) => {
        tab: string;
    };
    selectors: {
        tab: (state: any, props: any) => string;
    };
    values: {
        tab: string;
    };
    _isKea: true;
    __keaTypeGenInternalReducerActions: {
        "button (toolbar.dockLogic)": () => ({
            type: "button (toolbar.dockLogic)";
            payload: {
                value: boolean;
            };
        });
        "dock (toolbar.dockLogic)": () => ({
            type: "dock (toolbar.dockLogic)";
            payload: {
                value: boolean;
            };
        });
    };
}