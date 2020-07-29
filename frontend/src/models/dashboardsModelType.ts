// Auto-generated with kea-typegen. DO NOT EDIT!

export interface dashboardsModelType {
    key: any
    actionCreators: {
        delayedDeleteDashboard: (
            id: any
        ) => {
            type: 'delayed delete dashboard (models.dashboardsModel)'
            payload: { id: any }
        }
        setLastVisitedDashboardId: (
            id: any
        ) => {
            type: 'set last visited dashboard id (models.dashboardsModel)'
            payload: { id: any }
        }
        updateDashboardItem: (
            item: any
        ) => {
            type: 'update dashboard item (models.dashboardsModel)'
            payload: { item: any }
        }
        loadDashboards: () => {
            type: 'load dashboards (models.dashboardsModel)'
            payload: any
        }
        loadDashboardsSuccess: (rawDashboards: {}) => {
            type: 'load dashboards success (models.dashboardsModel)'
            payload: {
                rawDashboards: {}
            }
        }
        loadDashboardsFailure: (
            error: string
        ) => {
            type: 'load dashboards failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        addDashboard: ({
            name,
        }: any) => {
            type: 'add dashboard (models.dashboardsModel)'
            payload: any
        }
        addDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'add dashboard success (models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        addDashboardFailure: (
            error: string
        ) => {
            type: 'add dashboard failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        renameDashboard: ({
            id,
            name,
        }: any) => {
            type: 'rename dashboard (models.dashboardsModel)'
            payload: any
        }
        renameDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'rename dashboard success (models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        renameDashboardFailure: (
            error: string
        ) => {
            type: 'rename dashboard failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        setIsSharedDashboard: ({
            id,
            isShared,
        }: any) => {
            type: 'set is shared dashboard (models.dashboardsModel)'
            payload: any
        }
        setIsSharedDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'set is shared dashboard success (models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        setIsSharedDashboardFailure: (
            error: string
        ) => {
            type: 'set is shared dashboard failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        deleteDashboard: ({
            id,
        }: any) => {
            type: 'delete dashboard (models.dashboardsModel)'
            payload: any
        }
        deleteDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'delete dashboard success (models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        deleteDashboardFailure: (
            error: string
        ) => {
            type: 'delete dashboard failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        restoreDashboard: ({
            id,
        }: any) => {
            type: 'restore dashboard (models.dashboardsModel)'
            payload: any
        }
        restoreDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'restore dashboard success (models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        restoreDashboardFailure: (
            error: string
        ) => {
            type: 'restore dashboard failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        pinDashboard: (
            id: any
        ) => {
            type: 'pin dashboard (models.dashboardsModel)'
            payload: any
        }
        pinDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'pin dashboard success (models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        pinDashboardFailure: (
            error: string
        ) => {
            type: 'pin dashboard failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        unpinDashboard: (
            id: any
        ) => {
            type: 'unpin dashboard (models.dashboardsModel)'
            payload: any
        }
        unpinDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'unpin dashboard success (models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        unpinDashboardFailure: (
            error: string
        ) => {
            type: 'unpin dashboard failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'delayed delete dashboard (models.dashboardsModel)': 'delayedDeleteDashboard'
        'set last visited dashboard id (models.dashboardsModel)': 'setLastVisitedDashboardId'
        'update dashboard item (models.dashboardsModel)': 'updateDashboardItem'
        'load dashboards (models.dashboardsModel)': 'loadDashboards'
        'load dashboards success (models.dashboardsModel)': 'loadDashboardsSuccess'
        'load dashboards failure (models.dashboardsModel)': 'loadDashboardsFailure'
        'add dashboard (models.dashboardsModel)': 'addDashboard'
        'add dashboard success (models.dashboardsModel)': 'addDashboardSuccess'
        'add dashboard failure (models.dashboardsModel)': 'addDashboardFailure'
        'rename dashboard (models.dashboardsModel)': 'renameDashboard'
        'rename dashboard success (models.dashboardsModel)': 'renameDashboardSuccess'
        'rename dashboard failure (models.dashboardsModel)': 'renameDashboardFailure'
        'set is shared dashboard (models.dashboardsModel)': 'setIsSharedDashboard'
        'set is shared dashboard success (models.dashboardsModel)': 'setIsSharedDashboardSuccess'
        'set is shared dashboard failure (models.dashboardsModel)': 'setIsSharedDashboardFailure'
        'delete dashboard (models.dashboardsModel)': 'deleteDashboard'
        'delete dashboard success (models.dashboardsModel)': 'deleteDashboardSuccess'
        'delete dashboard failure (models.dashboardsModel)': 'deleteDashboardFailure'
        'restore dashboard (models.dashboardsModel)': 'restoreDashboard'
        'restore dashboard success (models.dashboardsModel)': 'restoreDashboardSuccess'
        'restore dashboard failure (models.dashboardsModel)': 'restoreDashboardFailure'
        'pin dashboard (models.dashboardsModel)': 'pinDashboard'
        'pin dashboard success (models.dashboardsModel)': 'pinDashboardSuccess'
        'pin dashboard failure (models.dashboardsModel)': 'pinDashboardFailure'
        'unpin dashboard (models.dashboardsModel)': 'unpinDashboard'
        'unpin dashboard success (models.dashboardsModel)': 'unpinDashboardSuccess'
        'unpin dashboard failure (models.dashboardsModel)': 'unpinDashboardFailure'
    }
    actionTypes: {
        delayedDeleteDashboard: 'delayed delete dashboard (models.dashboardsModel)'
        setLastVisitedDashboardId: 'set last visited dashboard id (models.dashboardsModel)'
        updateDashboardItem: 'update dashboard item (models.dashboardsModel)'
        loadDashboards: 'load dashboards (models.dashboardsModel)'
        loadDashboardsSuccess: 'load dashboards success (models.dashboardsModel)'
        loadDashboardsFailure: 'load dashboards failure (models.dashboardsModel)'
        addDashboard: 'add dashboard (models.dashboardsModel)'
        addDashboardSuccess: 'add dashboard success (models.dashboardsModel)'
        addDashboardFailure: 'add dashboard failure (models.dashboardsModel)'
        renameDashboard: 'rename dashboard (models.dashboardsModel)'
        renameDashboardSuccess: 'rename dashboard success (models.dashboardsModel)'
        renameDashboardFailure: 'rename dashboard failure (models.dashboardsModel)'
        setIsSharedDashboard: 'set is shared dashboard (models.dashboardsModel)'
        setIsSharedDashboardSuccess: 'set is shared dashboard success (models.dashboardsModel)'
        setIsSharedDashboardFailure: 'set is shared dashboard failure (models.dashboardsModel)'
        deleteDashboard: 'delete dashboard (models.dashboardsModel)'
        deleteDashboardSuccess: 'delete dashboard success (models.dashboardsModel)'
        deleteDashboardFailure: 'delete dashboard failure (models.dashboardsModel)'
        restoreDashboard: 'restore dashboard (models.dashboardsModel)'
        restoreDashboardSuccess: 'restore dashboard success (models.dashboardsModel)'
        restoreDashboardFailure: 'restore dashboard failure (models.dashboardsModel)'
        pinDashboard: 'pin dashboard (models.dashboardsModel)'
        pinDashboardSuccess: 'pin dashboard success (models.dashboardsModel)'
        pinDashboardFailure: 'pin dashboard failure (models.dashboardsModel)'
        unpinDashboard: 'unpin dashboard (models.dashboardsModel)'
        unpinDashboardSuccess: 'unpin dashboard success (models.dashboardsModel)'
        unpinDashboardFailure: 'unpin dashboard failure (models.dashboardsModel)'
    }
    actions: {
        delayedDeleteDashboard: (
            id: any
        ) => {
            type: 'delayed delete dashboard (models.dashboardsModel)'
            payload: { id: any }
        }
        setLastVisitedDashboardId: (
            id: any
        ) => {
            type: 'set last visited dashboard id (models.dashboardsModel)'
            payload: { id: any }
        }
        updateDashboardItem: (
            item: any
        ) => {
            type: 'update dashboard item (models.dashboardsModel)'
            payload: { item: any }
        }
        loadDashboards: () => {
            type: 'load dashboards (models.dashboardsModel)'
            payload: any
        }
        loadDashboardsSuccess: (rawDashboards: {}) => {
            type: 'load dashboards success (models.dashboardsModel)'
            payload: {
                rawDashboards: {}
            }
        }
        loadDashboardsFailure: (
            error: string
        ) => {
            type: 'load dashboards failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        addDashboard: ({
            name,
        }: any) => {
            type: 'add dashboard (models.dashboardsModel)'
            payload: any
        }
        addDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'add dashboard success (models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        addDashboardFailure: (
            error: string
        ) => {
            type: 'add dashboard failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        renameDashboard: ({
            id,
            name,
        }: any) => {
            type: 'rename dashboard (models.dashboardsModel)'
            payload: any
        }
        renameDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'rename dashboard success (models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        renameDashboardFailure: (
            error: string
        ) => {
            type: 'rename dashboard failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        setIsSharedDashboard: ({
            id,
            isShared,
        }: any) => {
            type: 'set is shared dashboard (models.dashboardsModel)'
            payload: any
        }
        setIsSharedDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'set is shared dashboard success (models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        setIsSharedDashboardFailure: (
            error: string
        ) => {
            type: 'set is shared dashboard failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        deleteDashboard: ({
            id,
        }: any) => {
            type: 'delete dashboard (models.dashboardsModel)'
            payload: any
        }
        deleteDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'delete dashboard success (models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        deleteDashboardFailure: (
            error: string
        ) => {
            type: 'delete dashboard failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        restoreDashboard: ({
            id,
        }: any) => {
            type: 'restore dashboard (models.dashboardsModel)'
            payload: any
        }
        restoreDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'restore dashboard success (models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        restoreDashboardFailure: (
            error: string
        ) => {
            type: 'restore dashboard failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        pinDashboard: (
            id: any
        ) => {
            type: 'pin dashboard (models.dashboardsModel)'
            payload: any
        }
        pinDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'pin dashboard success (models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        pinDashboardFailure: (
            error: string
        ) => {
            type: 'pin dashboard failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        unpinDashboard: (
            id: any
        ) => {
            type: 'unpin dashboard (models.dashboardsModel)'
            payload: any
        }
        unpinDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'unpin dashboard success (models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        unpinDashboardFailure: (
            error: string
        ) => {
            type: 'unpin dashboard failure (models.dashboardsModel)'
            payload: {
                error: string
            }
        }
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['models', 'dashboardsModel']
    pathString: 'models.dashboardsModel'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        rawDashboards: {}
        rawDashboardsLoading: boolean
        dashboard: any
        dashboardLoading: boolean
        redirect: boolean
        lastVisitedDashboardId: null
    }
    reducerOptions: any
    reducers: {
        rawDashboards: (state: {}, action: any, fullState: any) => {}
        rawDashboardsLoading: (state: boolean, action: any, fullState: any) => boolean
        dashboard: (state: any, action: any, fullState: any) => any
        dashboardLoading: (state: boolean, action: any, fullState: any) => boolean
        redirect: (state: boolean, action: any, fullState: any) => boolean
        lastVisitedDashboardId: (state: null, action: any, fullState: any) => null
    }
    selector: (
        state: any
    ) => {
        rawDashboards: {}
        rawDashboardsLoading: boolean
        dashboard: any
        dashboardLoading: boolean
        redirect: boolean
        lastVisitedDashboardId: null
    }
    selectors: {
        rawDashboards: (state: any, props: any) => {}
        rawDashboardsLoading: (state: any, props: any) => boolean
        dashboard: (state: any, props: any) => any
        dashboardLoading: (state: any, props: any) => boolean
        redirect: (state: any, props: any) => boolean
        lastVisitedDashboardId: (state: any, props: any) => null
        dashboards: (state: any, props: any) => any[]
        dashboardsLoading: (state: any, props: any) => any
        pinnedDashboards: (state: any, props: any) => any
    }
    values: {
        rawDashboards: {}
        rawDashboardsLoading: boolean
        dashboard: any
        dashboardLoading: boolean
        redirect: boolean
        lastVisitedDashboardId: null
        dashboards: any[]
        dashboardsLoading: any
        pinnedDashboards: any
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        dashboards: (arg1: any) => any[]
        dashboardsLoading: (arg1: any) => any
        pinnedDashboards: (arg1: any) => any
    }
}
