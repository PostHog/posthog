// Auto-generated with kea-typegen. DO NOT EDIT!

export interface dashboardsModelType {
    key: any
    actionCreators: {
        delayedDeleteDashboard: (
            id: any
        ) => {
            type: 'delayed delete dashboard (frontend.src.models.dashboardsModel)'
            payload: { id: any }
        }
        setLastVisitedDashboardId: (
            id: any
        ) => {
            type: 'set last visited dashboard id (frontend.src.models.dashboardsModel)'
            payload: { id: any }
        }
        updateDashboardItem: (
            item: any
        ) => {
            type: 'update dashboard item (frontend.src.models.dashboardsModel)'
            payload: { item: any }
        }
        loadDashboards: () => {
            type: 'load dashboards (frontend.src.models.dashboardsModel)'
            payload: any
        }
        loadDashboardsSuccess: (rawDashboards: {}) => {
            type: 'load dashboards success (frontend.src.models.dashboardsModel)'
            payload: {
                rawDashboards: {}
            }
        }
        loadDashboardsFailure: (
            error: string
        ) => {
            type: 'load dashboards failure (frontend.src.models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        addDashboard: ({
            name,
        }: any) => {
            type: 'add dashboard (frontend.src.models.dashboardsModel)'
            payload: any
        }
        addDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'add dashboard success (frontend.src.models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        addDashboardFailure: (
            error: string
        ) => {
            type: 'add dashboard failure (frontend.src.models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        renameDashboard: ({
            id,
            name,
        }: any) => {
            type: 'rename dashboard (frontend.src.models.dashboardsModel)'
            payload: any
        }
        renameDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'rename dashboard success (frontend.src.models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        renameDashboardFailure: (
            error: string
        ) => {
            type: 'rename dashboard failure (frontend.src.models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        setIsSharedDashboard: ({
            id,
            isShared,
        }: any) => {
            type: 'set is shared dashboard (frontend.src.models.dashboardsModel)'
            payload: any
        }
        setIsSharedDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'set is shared dashboard success (frontend.src.models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        setIsSharedDashboardFailure: (
            error: string
        ) => {
            type: 'set is shared dashboard failure (frontend.src.models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        deleteDashboard: ({
            id,
        }: any) => {
            type: 'delete dashboard (frontend.src.models.dashboardsModel)'
            payload: any
        }
        deleteDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'delete dashboard success (frontend.src.models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        deleteDashboardFailure: (
            error: string
        ) => {
            type: 'delete dashboard failure (frontend.src.models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        restoreDashboard: ({
            id,
        }: any) => {
            type: 'restore dashboard (frontend.src.models.dashboardsModel)'
            payload: any
        }
        restoreDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'restore dashboard success (frontend.src.models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        restoreDashboardFailure: (
            error: string
        ) => {
            type: 'restore dashboard failure (frontend.src.models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        pinDashboard: (
            id: any
        ) => {
            type: 'pin dashboard (frontend.src.models.dashboardsModel)'
            payload: any
        }
        pinDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'pin dashboard success (frontend.src.models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        pinDashboardFailure: (
            error: string
        ) => {
            type: 'pin dashboard failure (frontend.src.models.dashboardsModel)'
            payload: {
                error: string
            }
        }
        unpinDashboard: (
            id: any
        ) => {
            type: 'unpin dashboard (frontend.src.models.dashboardsModel)'
            payload: any
        }
        unpinDashboardSuccess: (
            dashboard: any
        ) => {
            type: 'unpin dashboard success (frontend.src.models.dashboardsModel)'
            payload: {
                dashboard: any
            }
        }
        unpinDashboardFailure: (
            error: string
        ) => {
            type: 'unpin dashboard failure (frontend.src.models.dashboardsModel)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'delayed delete dashboard (frontend.src.models.dashboardsModel)': 'delayedDeleteDashboard'
        'set last visited dashboard id (frontend.src.models.dashboardsModel)': 'setLastVisitedDashboardId'
        'update dashboard item (frontend.src.models.dashboardsModel)': 'updateDashboardItem'
        'load dashboards (frontend.src.models.dashboardsModel)': 'loadDashboards'
        'load dashboards success (frontend.src.models.dashboardsModel)': 'loadDashboardsSuccess'
        'load dashboards failure (frontend.src.models.dashboardsModel)': 'loadDashboardsFailure'
        'add dashboard (frontend.src.models.dashboardsModel)': 'addDashboard'
        'add dashboard success (frontend.src.models.dashboardsModel)': 'addDashboardSuccess'
        'add dashboard failure (frontend.src.models.dashboardsModel)': 'addDashboardFailure'
        'rename dashboard (frontend.src.models.dashboardsModel)': 'renameDashboard'
        'rename dashboard success (frontend.src.models.dashboardsModel)': 'renameDashboardSuccess'
        'rename dashboard failure (frontend.src.models.dashboardsModel)': 'renameDashboardFailure'
        'set is shared dashboard (frontend.src.models.dashboardsModel)': 'setIsSharedDashboard'
        'set is shared dashboard success (frontend.src.models.dashboardsModel)': 'setIsSharedDashboardSuccess'
        'set is shared dashboard failure (frontend.src.models.dashboardsModel)': 'setIsSharedDashboardFailure'
        'delete dashboard (frontend.src.models.dashboardsModel)': 'deleteDashboard'
        'delete dashboard success (frontend.src.models.dashboardsModel)': 'deleteDashboardSuccess'
        'delete dashboard failure (frontend.src.models.dashboardsModel)': 'deleteDashboardFailure'
        'restore dashboard (frontend.src.models.dashboardsModel)': 'restoreDashboard'
        'restore dashboard success (frontend.src.models.dashboardsModel)': 'restoreDashboardSuccess'
        'restore dashboard failure (frontend.src.models.dashboardsModel)': 'restoreDashboardFailure'
        'pin dashboard (frontend.src.models.dashboardsModel)': 'pinDashboard'
        'pin dashboard success (frontend.src.models.dashboardsModel)': 'pinDashboardSuccess'
        'pin dashboard failure (frontend.src.models.dashboardsModel)': 'pinDashboardFailure'
        'unpin dashboard (frontend.src.models.dashboardsModel)': 'unpinDashboard'
        'unpin dashboard success (frontend.src.models.dashboardsModel)': 'unpinDashboardSuccess'
        'unpin dashboard failure (frontend.src.models.dashboardsModel)': 'unpinDashboardFailure'
    }
    actionTypes: {
        delayedDeleteDashboard: 'delayed delete dashboard (frontend.src.models.dashboardsModel)'
        setLastVisitedDashboardId: 'set last visited dashboard id (frontend.src.models.dashboardsModel)'
        updateDashboardItem: 'update dashboard item (frontend.src.models.dashboardsModel)'
        loadDashboards: 'load dashboards (frontend.src.models.dashboardsModel)'
        loadDashboardsSuccess: 'load dashboards success (frontend.src.models.dashboardsModel)'
        loadDashboardsFailure: 'load dashboards failure (frontend.src.models.dashboardsModel)'
        addDashboard: 'add dashboard (frontend.src.models.dashboardsModel)'
        addDashboardSuccess: 'add dashboard success (frontend.src.models.dashboardsModel)'
        addDashboardFailure: 'add dashboard failure (frontend.src.models.dashboardsModel)'
        renameDashboard: 'rename dashboard (frontend.src.models.dashboardsModel)'
        renameDashboardSuccess: 'rename dashboard success (frontend.src.models.dashboardsModel)'
        renameDashboardFailure: 'rename dashboard failure (frontend.src.models.dashboardsModel)'
        setIsSharedDashboard: 'set is shared dashboard (frontend.src.models.dashboardsModel)'
        setIsSharedDashboardSuccess: 'set is shared dashboard success (frontend.src.models.dashboardsModel)'
        setIsSharedDashboardFailure: 'set is shared dashboard failure (frontend.src.models.dashboardsModel)'
        deleteDashboard: 'delete dashboard (frontend.src.models.dashboardsModel)'
        deleteDashboardSuccess: 'delete dashboard success (frontend.src.models.dashboardsModel)'
        deleteDashboardFailure: 'delete dashboard failure (frontend.src.models.dashboardsModel)'
        restoreDashboard: 'restore dashboard (frontend.src.models.dashboardsModel)'
        restoreDashboardSuccess: 'restore dashboard success (frontend.src.models.dashboardsModel)'
        restoreDashboardFailure: 'restore dashboard failure (frontend.src.models.dashboardsModel)'
        pinDashboard: 'pin dashboard (frontend.src.models.dashboardsModel)'
        pinDashboardSuccess: 'pin dashboard success (frontend.src.models.dashboardsModel)'
        pinDashboardFailure: 'pin dashboard failure (frontend.src.models.dashboardsModel)'
        unpinDashboard: 'unpin dashboard (frontend.src.models.dashboardsModel)'
        unpinDashboardSuccess: 'unpin dashboard success (frontend.src.models.dashboardsModel)'
        unpinDashboardFailure: 'unpin dashboard failure (frontend.src.models.dashboardsModel)'
    }
    actions: {
        delayedDeleteDashboard: (id: any) => void
        setLastVisitedDashboardId: (id: any) => void
        updateDashboardItem: (item: any) => void
        loadDashboards: () => void
        loadDashboardsSuccess: (rawDashboards: {}) => void
        loadDashboardsFailure: (error: string) => void
        addDashboard: ({ name }: any) => void
        addDashboardSuccess: (dashboard: any) => void
        addDashboardFailure: (error: string) => void
        renameDashboard: ({ id, name }: any) => void
        renameDashboardSuccess: (dashboard: any) => void
        renameDashboardFailure: (error: string) => void
        setIsSharedDashboard: ({ id, isShared }: any) => void
        setIsSharedDashboardSuccess: (dashboard: any) => void
        setIsSharedDashboardFailure: (error: string) => void
        deleteDashboard: ({ id }: any) => void
        deleteDashboardSuccess: (dashboard: any) => void
        deleteDashboardFailure: (error: string) => void
        restoreDashboard: ({ id }: any) => void
        restoreDashboardSuccess: (dashboard: any) => void
        restoreDashboardFailure: (error: string) => void
        pinDashboard: (id: any) => void
        pinDashboardSuccess: (dashboard: any) => void
        pinDashboardFailure: (error: string) => void
        unpinDashboard: (id: any) => void
        unpinDashboardSuccess: (dashboard: any) => void
        unpinDashboardFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'models', 'dashboardsModel']
    pathString: 'frontend.src.models.dashboardsModel'
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
