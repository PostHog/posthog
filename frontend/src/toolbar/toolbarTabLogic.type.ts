// Auto-generated with kea-typegen. DO NOT EDIT!

export interface toolbarTabLogicType {
    key: any;
    actionCreators: {
        setTab: (tab: string) => ({
            type: "set tab (frontend.src.toolbar.toolbarTabLogic)";
            payload: { tab: string; };
        });
    };
    actionKeys: any;
    actions: {
        setTab: (tab: string) => ({
            type: "set tab (frontend.src.toolbar.toolbarTabLogic)";
            payload: { tab: string; };
        });
    };
    cache: Record<string, any>;
    connections: any;
    constants: any;
    defaults: any;
    events: any;
    path: ["frontend", "src", "toolbar", "toolbarTabLogic"];
    pathString: "frontend.src.toolbar.toolbarTabLogic";
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
}