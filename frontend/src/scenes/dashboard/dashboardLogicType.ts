// Auto-generated with kea-typegen. DO NOT EDIT!

export interface dashboardLogicType {
    key: any
    actionCreators: {
        addNewDashboard: () => {
            type: 'add new dashboard (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: {
                value: boolean
            }
        }
        renameDashboard: () => {
            type: 'rename dashboard (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: {
                value: boolean
            }
        }
        renameDashboardItem: (
            id: any
        ) => {
            type: 'rename dashboard item (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: { id: any }
        }
        renameDashboardItemSuccess: (
            item: any
        ) => {
            type: 'rename dashboard item success (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: { item: any }
        }
        setIsSharedDashboard: (
            id: any,
            isShared: any
        ) => {
            type: 'set is shared dashboard (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: { id: any; isShared: any }
        }
        duplicateDashboardItem: (
            id: any,
            dashboardId: any,
            move?: any
        ) => {
            type: 'duplicate dashboard item (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: { id: any; dashboardId: any; move: boolean }
        }
        duplicateDashboardItemSuccess: (
            item: any
        ) => {
            type: 'duplicate dashboard item success (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: { item: any }
        }
        updateLayouts: (
            layouts: any
        ) => {
            type: 'update layouts (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: { layouts: any }
        }
        updateContainerWidth: (
            containerWidth: any,
            columns: any
        ) => {
            type: 'update container width (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: { containerWidth: any; columns: any }
        }
        saveLayouts: () => {
            type: 'save layouts (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: {
                value: boolean
            }
        }
        updateItemColor: (
            id: any,
            color: any
        ) => {
            type: 'update item color (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: { id: any; color: any }
        }
        enableDragging: () => {
            type: 'enable dragging (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: {
                value: boolean
            }
        }
        enableWobblyDragging: () => {
            type: 'enable wobbly dragging (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: {
                value: boolean
            }
        }
        disableDragging: () => {
            type: 'disable dragging (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: {
                value: boolean
            }
        }
        refreshDashboardItem: (
            id: any
        ) => {
            type: 'refresh dashboard item (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: { id: any }
        }
        loadDashboardItems: () => {
            type: 'load dashboard items (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: any
        }
        loadDashboardItemsSuccess: (
            allItems: never[]
        ) => {
            type: 'load dashboard items success (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: {
                allItems: never[]
            }
        }
        loadDashboardItemsFailure: (
            error: string
        ) => {
            type: 'load dashboard items failure (frontend.src.scenes.dashboard.dashboardLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'add new dashboard (frontend.src.scenes.dashboard.dashboardLogic)': 'addNewDashboard'
        'rename dashboard (frontend.src.scenes.dashboard.dashboardLogic)': 'renameDashboard'
        'rename dashboard item (frontend.src.scenes.dashboard.dashboardLogic)': 'renameDashboardItem'
        'rename dashboard item success (frontend.src.scenes.dashboard.dashboardLogic)': 'renameDashboardItemSuccess'
        'set is shared dashboard (frontend.src.scenes.dashboard.dashboardLogic)': 'setIsSharedDashboard'
        'duplicate dashboard item (frontend.src.scenes.dashboard.dashboardLogic)': 'duplicateDashboardItem'
        'duplicate dashboard item success (frontend.src.scenes.dashboard.dashboardLogic)': 'duplicateDashboardItemSuccess'
        'update layouts (frontend.src.scenes.dashboard.dashboardLogic)': 'updateLayouts'
        'update container width (frontend.src.scenes.dashboard.dashboardLogic)': 'updateContainerWidth'
        'save layouts (frontend.src.scenes.dashboard.dashboardLogic)': 'saveLayouts'
        'update item color (frontend.src.scenes.dashboard.dashboardLogic)': 'updateItemColor'
        'enable dragging (frontend.src.scenes.dashboard.dashboardLogic)': 'enableDragging'
        'enable wobbly dragging (frontend.src.scenes.dashboard.dashboardLogic)': 'enableWobblyDragging'
        'disable dragging (frontend.src.scenes.dashboard.dashboardLogic)': 'disableDragging'
        'refresh dashboard item (frontend.src.scenes.dashboard.dashboardLogic)': 'refreshDashboardItem'
        'load dashboard items (frontend.src.scenes.dashboard.dashboardLogic)': 'loadDashboardItems'
        'load dashboard items success (frontend.src.scenes.dashboard.dashboardLogic)': 'loadDashboardItemsSuccess'
        'load dashboard items failure (frontend.src.scenes.dashboard.dashboardLogic)': 'loadDashboardItemsFailure'
    }
    actionTypes: {
        addNewDashboard: 'add new dashboard (frontend.src.scenes.dashboard.dashboardLogic)'
        renameDashboard: 'rename dashboard (frontend.src.scenes.dashboard.dashboardLogic)'
        renameDashboardItem: 'rename dashboard item (frontend.src.scenes.dashboard.dashboardLogic)'
        renameDashboardItemSuccess: 'rename dashboard item success (frontend.src.scenes.dashboard.dashboardLogic)'
        setIsSharedDashboard: 'set is shared dashboard (frontend.src.scenes.dashboard.dashboardLogic)'
        duplicateDashboardItem: 'duplicate dashboard item (frontend.src.scenes.dashboard.dashboardLogic)'
        duplicateDashboardItemSuccess: 'duplicate dashboard item success (frontend.src.scenes.dashboard.dashboardLogic)'
        updateLayouts: 'update layouts (frontend.src.scenes.dashboard.dashboardLogic)'
        updateContainerWidth: 'update container width (frontend.src.scenes.dashboard.dashboardLogic)'
        saveLayouts: 'save layouts (frontend.src.scenes.dashboard.dashboardLogic)'
        updateItemColor: 'update item color (frontend.src.scenes.dashboard.dashboardLogic)'
        enableDragging: 'enable dragging (frontend.src.scenes.dashboard.dashboardLogic)'
        enableWobblyDragging: 'enable wobbly dragging (frontend.src.scenes.dashboard.dashboardLogic)'
        disableDragging: 'disable dragging (frontend.src.scenes.dashboard.dashboardLogic)'
        refreshDashboardItem: 'refresh dashboard item (frontend.src.scenes.dashboard.dashboardLogic)'
        loadDashboardItems: 'load dashboard items (frontend.src.scenes.dashboard.dashboardLogic)'
        loadDashboardItemsSuccess: 'load dashboard items success (frontend.src.scenes.dashboard.dashboardLogic)'
        loadDashboardItemsFailure: 'load dashboard items failure (frontend.src.scenes.dashboard.dashboardLogic)'
    }
    actions: {
        addNewDashboard: () => void
        renameDashboard: () => void
        renameDashboardItem: (id: any) => void
        renameDashboardItemSuccess: (item: any) => void
        setIsSharedDashboard: (id: any, isShared: any) => void
        duplicateDashboardItem: (id: any, dashboardId: any, move?: any) => void
        duplicateDashboardItemSuccess: (item: any) => void
        updateLayouts: (layouts: any) => void
        updateContainerWidth: (containerWidth: any, columns: any) => void
        saveLayouts: () => void
        updateItemColor: (id: any, color: any) => void
        enableDragging: () => void
        enableWobblyDragging: () => void
        disableDragging: () => void
        refreshDashboardItem: (id: any) => void
        loadDashboardItems: () => void
        loadDashboardItemsSuccess: (allItems: never[]) => void
        loadDashboardItemsFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'dashboard', 'dashboardLogic']
    pathString: 'frontend.src.scenes.dashboard.dashboardLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        allItems: never[]
        allItemsLoading: boolean
        draggingEnabled: () => 'off' | 'on'
        containerWidth: null
        columns: null
    }
    reducerOptions: any
    reducers: {
        allItems: (state: never[], action: any, fullState: any) => never[]
        allItemsLoading: (state: boolean, action: any, fullState: any) => boolean
        draggingEnabled: (state: () => 'off' | 'on', action: any, fullState: any) => () => 'off' | 'on'
        containerWidth: (state: null, action: any, fullState: any) => null
        columns: (state: null, action: any, fullState: any) => null
    }
    selector: (
        state: any
    ) => {
        allItems: never[]
        allItemsLoading: boolean
        draggingEnabled: () => 'off' | 'on'
        containerWidth: null
        columns: null
    }
    selectors: {
        allItems: (state: any, props: any) => never[]
        allItemsLoading: (state: any, props: any) => boolean
        draggingEnabled: (state: any, props: any) => () => 'off' | 'on'
        containerWidth: (state: any, props: any) => null
        columns: (state: any, props: any) => null
        items: (state: any, props: any) => any
        itemsLoading: (state: any, props: any) => any
        dashboard: (state: any, props: any) => any
        breakpoints: (state: any, props: any) => { lg: number; sm: number; xs: number; xxs: number }
        cols: (state: any, props: any) => { lg: number; sm: number; xs: number; xxs: number }
        sizeKey: (state: any, props: any) => string | undefined
        layouts: (state: any, props: any) => {}
        layout: (state: any, props: any) => any
        layoutForItem: (state: any, props: any) => {}
    }
    values: {
        allItems: never[]
        allItemsLoading: boolean
        draggingEnabled: () => 'off' | 'on'
        containerWidth: null
        columns: null
        items: any
        itemsLoading: any
        dashboard: any
        breakpoints: { lg: number; sm: number; xs: number; xxs: number }
        cols: { lg: number; sm: number; xs: number; xxs: number }
        sizeKey: string | undefined
        layouts: {}
        layout: any
        layoutForItem: {}
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        items: (arg1: any) => any
        itemsLoading: (arg1: any) => any
        dashboard: (arg1: any, arg2: any) => any
        sizeKey: (arg1: any, arg2: any) => string | undefined
        layouts: (arg1: any, arg2: any) => {}
        layout: (arg1: any, arg2: any) => any
        layoutForItem: (arg1: any) => {}
    }
}
