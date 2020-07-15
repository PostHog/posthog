// Auto-generated with kea-typegen v0.0.11. DO NOT EDIT!

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
}