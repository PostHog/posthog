// Auto-generated with kea-typegen. DO NOT EDIT!

export interface dashboardsModelType<Dashboard,  DashboardItem> {
    key: any;
    actionCreators: {
        delayedDeleteDashboard: (id: number) => ({
            type: "delayed delete dashboard (models.dashboardsModel)";
            payload: { id: number; };
        });
        setLastVisitedDashboardId: (id: number) => ({
            type: "set last visited dashboard id (models.dashboardsModel)";
            payload: { id: number; };
        });
        updateDashboardItem: (item: DashboardItem) => ({
            type: "update dashboard item (models.dashboardsModel)";
            payload: { item: DashboardItem; };
        });
        loadDashboards: () => ({
            type: "load dashboards (models.dashboardsModel)";
            payload: any;
        });
        loadDashboardsSuccess: (rawDashboards: Record<string, Dashboard>) => ({
            type: "load dashboards success (models.dashboardsModel)";
            payload: {
                rawDashboards: Record<string, Dashboard>;
            };
        });
        loadDashboardsFailure: (error: string) => ({
            type: "load dashboards failure (models.dashboardsModel)";
            payload: {
                error: string;
            };
        });
        addDashboard: ({ name }: {
            name: string;
        }) => ({
            type: "add dashboard (models.dashboardsModel)";
            payload: {
                name: string;
            };
        });
        addDashboardSuccess: (dashboard: Dashboard | null) => ({
            type: "add dashboard success (models.dashboardsModel)";
            payload: {
                dashboard: Dashboard | null;
            };
        });
        addDashboardFailure: (error: string) => ({
            type: "add dashboard failure (models.dashboardsModel)";
            payload: {
                error: string;
            };
        });
        renameDashboard: ({ id, name }: {
            id: number;
            name: string;
        }) => ({
            type: "rename dashboard (models.dashboardsModel)";
            payload: {
                id: number;
                name: string;
            };
        });
        renameDashboardSuccess: (dashboard: Dashboard | null) => ({
            type: "rename dashboard success (models.dashboardsModel)";
            payload: {
                dashboard: Dashboard | null;
            };
        });
        renameDashboardFailure: (error: string) => ({
            type: "rename dashboard failure (models.dashboardsModel)";
            payload: {
                error: string;
            };
        });
        deleteDashboard: ({ id }: {
            id: number;
        }) => ({
            type: "delete dashboard (models.dashboardsModel)";
            payload: {
                id: number;
            };
        });
        deleteDashboardSuccess: (dashboard: Dashboard | null) => ({
            type: "delete dashboard success (models.dashboardsModel)";
            payload: {
                dashboard: Dashboard | null;
            };
        });
        deleteDashboardFailure: (error: string) => ({
            type: "delete dashboard failure (models.dashboardsModel)";
            payload: {
                error: string;
            };
        });
        restoreDashboard: ({ id }: {
            id: number;
        }) => ({
            type: "restore dashboard (models.dashboardsModel)";
            payload: {
                id: number;
            };
        });
        restoreDashboardSuccess: (dashboard: Dashboard | null) => ({
            type: "restore dashboard success (models.dashboardsModel)";
            payload: {
                dashboard: Dashboard | null;
            };
        });
        restoreDashboardFailure: (error: string) => ({
            type: "restore dashboard failure (models.dashboardsModel)";
            payload: {
                error: string;
            };
        });
        pinDashboard: (id: number) => ({
            type: "pin dashboard (models.dashboardsModel)";
            payload: number;
        });
        pinDashboardSuccess: (dashboard: Dashboard | null) => ({
            type: "pin dashboard success (models.dashboardsModel)";
            payload: {
                dashboard: Dashboard | null;
            };
        });
        pinDashboardFailure: (error: string) => ({
            type: "pin dashboard failure (models.dashboardsModel)";
            payload: {
                error: string;
            };
        });
        unpinDashboard: (id: number) => ({
            type: "unpin dashboard (models.dashboardsModel)";
            payload: number;
        });
        unpinDashboardSuccess: (dashboard: Dashboard | null) => ({
            type: "unpin dashboard success (models.dashboardsModel)";
            payload: {
                dashboard: Dashboard | null;
            };
        });
        unpinDashboardFailure: (error: string) => ({
            type: "unpin dashboard failure (models.dashboardsModel)";
            payload: {
                error: string;
            };
        });
    };
    actionKeys: {
        "delayed delete dashboard (models.dashboardsModel)": "delayedDeleteDashboard";
        "set last visited dashboard id (models.dashboardsModel)": "setLastVisitedDashboardId";
        "update dashboard item (models.dashboardsModel)": "updateDashboardItem";
        "load dashboards (models.dashboardsModel)": "loadDashboards";
        "load dashboards success (models.dashboardsModel)": "loadDashboardsSuccess";
        "load dashboards failure (models.dashboardsModel)": "loadDashboardsFailure";
        "add dashboard (models.dashboardsModel)": "addDashboard";
        "add dashboard success (models.dashboardsModel)": "addDashboardSuccess";
        "add dashboard failure (models.dashboardsModel)": "addDashboardFailure";
        "rename dashboard (models.dashboardsModel)": "renameDashboard";
        "rename dashboard success (models.dashboardsModel)": "renameDashboardSuccess";
        "rename dashboard failure (models.dashboardsModel)": "renameDashboardFailure";
        "delete dashboard (models.dashboardsModel)": "deleteDashboard";
        "delete dashboard success (models.dashboardsModel)": "deleteDashboardSuccess";
        "delete dashboard failure (models.dashboardsModel)": "deleteDashboardFailure";
        "restore dashboard (models.dashboardsModel)": "restoreDashboard";
        "restore dashboard success (models.dashboardsModel)": "restoreDashboardSuccess";
        "restore dashboard failure (models.dashboardsModel)": "restoreDashboardFailure";
        "pin dashboard (models.dashboardsModel)": "pinDashboard";
        "pin dashboard success (models.dashboardsModel)": "pinDashboardSuccess";
        "pin dashboard failure (models.dashboardsModel)": "pinDashboardFailure";
        "unpin dashboard (models.dashboardsModel)": "unpinDashboard";
        "unpin dashboard success (models.dashboardsModel)": "unpinDashboardSuccess";
        "unpin dashboard failure (models.dashboardsModel)": "unpinDashboardFailure";
    };
    actionTypes: {
        delayedDeleteDashboard: "delayed delete dashboard (models.dashboardsModel)";
        setLastVisitedDashboardId: "set last visited dashboard id (models.dashboardsModel)";
        updateDashboardItem: "update dashboard item (models.dashboardsModel)";
        loadDashboards: "load dashboards (models.dashboardsModel)";
        loadDashboardsSuccess: "load dashboards success (models.dashboardsModel)";
        loadDashboardsFailure: "load dashboards failure (models.dashboardsModel)";
        addDashboard: "add dashboard (models.dashboardsModel)";
        addDashboardSuccess: "add dashboard success (models.dashboardsModel)";
        addDashboardFailure: "add dashboard failure (models.dashboardsModel)";
        renameDashboard: "rename dashboard (models.dashboardsModel)";
        renameDashboardSuccess: "rename dashboard success (models.dashboardsModel)";
        renameDashboardFailure: "rename dashboard failure (models.dashboardsModel)";
        deleteDashboard: "delete dashboard (models.dashboardsModel)";
        deleteDashboardSuccess: "delete dashboard success (models.dashboardsModel)";
        deleteDashboardFailure: "delete dashboard failure (models.dashboardsModel)";
        restoreDashboard: "restore dashboard (models.dashboardsModel)";
        restoreDashboardSuccess: "restore dashboard success (models.dashboardsModel)";
        restoreDashboardFailure: "restore dashboard failure (models.dashboardsModel)";
        pinDashboard: "pin dashboard (models.dashboardsModel)";
        pinDashboardSuccess: "pin dashboard success (models.dashboardsModel)";
        pinDashboardFailure: "pin dashboard failure (models.dashboardsModel)";
        unpinDashboard: "unpin dashboard (models.dashboardsModel)";
        unpinDashboardSuccess: "unpin dashboard success (models.dashboardsModel)";
        unpinDashboardFailure: "unpin dashboard failure (models.dashboardsModel)";
    };
    actions: {
        delayedDeleteDashboard: (id: number) => ({
            type: "delayed delete dashboard (models.dashboardsModel)";
            payload: { id: number; };
        });
        setLastVisitedDashboardId: (id: number) => ({
            type: "set last visited dashboard id (models.dashboardsModel)";
            payload: { id: number; };
        });
        updateDashboardItem: (item: DashboardItem) => ({
            type: "update dashboard item (models.dashboardsModel)";
            payload: { item: DashboardItem; };
        });
        loadDashboards: () => ({
            type: "load dashboards (models.dashboardsModel)";
            payload: any;
        });
        loadDashboardsSuccess: (rawDashboards: Record<string, Dashboard>) => ({
            type: "load dashboards success (models.dashboardsModel)";
            payload: {
                rawDashboards: Record<string, Dashboard>;
            };
        });
        loadDashboardsFailure: (error: string) => ({
            type: "load dashboards failure (models.dashboardsModel)";
            payload: {
                error: string;
            };
        });
        addDashboard: ({ name }: {
            name: string;
        }) => ({
            type: "add dashboard (models.dashboardsModel)";
            payload: {
                name: string;
            };
        });
        addDashboardSuccess: (dashboard: Dashboard | null) => ({
            type: "add dashboard success (models.dashboardsModel)";
            payload: {
                dashboard: Dashboard | null;
            };
        });
        addDashboardFailure: (error: string) => ({
            type: "add dashboard failure (models.dashboardsModel)";
            payload: {
                error: string;
            };
        });
        renameDashboard: ({ id, name }: {
            id: number;
            name: string;
        }) => ({
            type: "rename dashboard (models.dashboardsModel)";
            payload: {
                id: number;
                name: string;
            };
        });
        renameDashboardSuccess: (dashboard: Dashboard | null) => ({
            type: "rename dashboard success (models.dashboardsModel)";
            payload: {
                dashboard: Dashboard | null;
            };
        });
        renameDashboardFailure: (error: string) => ({
            type: "rename dashboard failure (models.dashboardsModel)";
            payload: {
                error: string;
            };
        });
        deleteDashboard: ({ id }: {
            id: number;
        }) => ({
            type: "delete dashboard (models.dashboardsModel)";
            payload: {
                id: number;
            };
        });
        deleteDashboardSuccess: (dashboard: Dashboard | null) => ({
            type: "delete dashboard success (models.dashboardsModel)";
            payload: {
                dashboard: Dashboard | null;
            };
        });
        deleteDashboardFailure: (error: string) => ({
            type: "delete dashboard failure (models.dashboardsModel)";
            payload: {
                error: string;
            };
        });
        restoreDashboard: ({ id }: {
            id: number;
        }) => ({
            type: "restore dashboard (models.dashboardsModel)";
            payload: {
                id: number;
            };
        });
        restoreDashboardSuccess: (dashboard: Dashboard | null) => ({
            type: "restore dashboard success (models.dashboardsModel)";
            payload: {
                dashboard: Dashboard | null;
            };
        });
        restoreDashboardFailure: (error: string) => ({
            type: "restore dashboard failure (models.dashboardsModel)";
            payload: {
                error: string;
            };
        });
        pinDashboard: (id: number) => ({
            type: "pin dashboard (models.dashboardsModel)";
            payload: number;
        });
        pinDashboardSuccess: (dashboard: Dashboard | null) => ({
            type: "pin dashboard success (models.dashboardsModel)";
            payload: {
                dashboard: Dashboard | null;
            };
        });
        pinDashboardFailure: (error: string) => ({
            type: "pin dashboard failure (models.dashboardsModel)";
            payload: {
                error: string;
            };
        });
        unpinDashboard: (id: number) => ({
            type: "unpin dashboard (models.dashboardsModel)";
            payload: number;
        });
        unpinDashboardSuccess: (dashboard: Dashboard | null) => ({
            type: "unpin dashboard success (models.dashboardsModel)";
            payload: {
                dashboard: Dashboard | null;
            };
        });
        unpinDashboardFailure: (error: string) => ({
            type: "unpin dashboard failure (models.dashboardsModel)";
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
    path: ["models", "dashboardsModel"];
    pathString: "models.dashboardsModel";
    propTypes: any;
    props: Record<string, any>;
    reducer: (state: any, action: () => any, fullState: any) => {
        rawDashboards: Record<string, Dashboard>;
        rawDashboardsLoading: boolean;
        dashboard: Dashboard | null;
        dashboardLoading: boolean;
        redirect: boolean;
        lastVisitedDashboardId: null;
    };
    reducerOptions: any;
    reducers: {
        rawDashboards: (state: Record<string, Dashboard>, action: any, fullState: any) => Record<string, Dashboard>;
        rawDashboardsLoading: (state: boolean, action: any, fullState: any) => boolean;
        dashboard: (state: Dashboard | null, action: any, fullState: any) => Dashboard | null;
        dashboardLoading: (state: boolean, action: any, fullState: any) => boolean;
        redirect: (state: boolean, action: any, fullState: any) => boolean;
        lastVisitedDashboardId: (state: null, action: any, fullState: any) => null;
    };
    selector: (state: any) => {
        rawDashboards: Record<string, Dashboard>;
        rawDashboardsLoading: boolean;
        dashboard: Dashboard | null;
        dashboardLoading: boolean;
        redirect: boolean;
        lastVisitedDashboardId: null;
    };
    selectors: {
        rawDashboards: (state: any, props: any) => Record<string, Dashboard>;
        rawDashboardsLoading: (state: any, props: any) => boolean;
        dashboard: (state: any, props: any) => Dashboard | null;
        dashboardLoading: (state: any, props: any) => boolean;
        redirect: (state: any, props: any) => boolean;
        lastVisitedDashboardId: (state: any, props: any) => null;
        dashboards: (state: any, props: any) => Dashboard[];
        dashboardsLoading: (state: any, props: any) => boolean;
        pinnedDashboards: (state: any, props: any) => Dashboard[];
    };
    values: {
        rawDashboards: Record<string, Dashboard>;
        rawDashboardsLoading: boolean;
        dashboard: Dashboard | null;
        dashboardLoading: boolean;
        redirect: boolean;
        lastVisitedDashboardId: null;
        dashboards: Dashboard[];
        dashboardsLoading: boolean;
        pinnedDashboards: Dashboard[];
    };
    _isKea: true;
    __keaTypeGenInternalSelectorTypes: {
        dashboards: (arg1: Record<string, Dashboard>) => Dashboard[];
        dashboardsLoading: (arg1: boolean) => boolean;
        pinnedDashboards: (arg1: Dashboard[]) => Dashboard[];
    };
}