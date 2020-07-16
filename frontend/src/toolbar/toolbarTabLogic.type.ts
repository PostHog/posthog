// Auto-generated with kea-typegen. DO NOT EDIT!

export interface toolbarTabLogicType {
    actionCreators: {
        setTab: (tab: string) => ({
            type: "set tab (frontend.src.toolbar.toolbarTabLogic)";
            payload: { tab: string; };
        });
    };
    actions: {
        setTab: (tab: string) => ({
            type: "set tab (frontend.src.toolbar.toolbarTabLogic)";
            payload: { tab: string; };
        });
    };
    cache: Record<string, any>;
    path: ["frontend", "src", "toolbar", "toolbarTabLogic"];
    pathString: "frontend.src.toolbar.toolbarTabLogic";
    props: Record<string, any>;
    reducer: (state: any, action: () => any, fullState: any) => {
        tab: string;
    };
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