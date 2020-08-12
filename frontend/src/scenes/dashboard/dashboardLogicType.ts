// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic, BreakPointFunction } from 'kea'

export interface dashboardLogicType extends Logic {
    actionCreators: {
        addNewDashboard: () => {
            type: 'add new dashboard (scenes.dashboard.dashboardLogic)'
            payload: {
                value: boolean
            }
        }
        renameDashboard: () => {
            type: 'rename dashboard (scenes.dashboard.dashboardLogic)'
            payload: {
                value: boolean
            }
        }
        renameDashboardItem: (
            id: any
        ) => {
            type: 'rename dashboard item (scenes.dashboard.dashboardLogic)'
            payload: {
                id: any
            }
        }
        renameDashboardItemSuccess: (
            item: any
        ) => {
            type: 'rename dashboard item success (scenes.dashboard.dashboardLogic)'
            payload: {
                item: any
            }
        }
        setIsSharedDashboard: (
            id: any,
            isShared: any
        ) => {
            type: 'set is shared dashboard (scenes.dashboard.dashboardLogic)'
            payload: {
                id: any
                isShared: any
            }
        }
        duplicateDashboardItem: (
            id: any,
            dashboardId: any,
            move?: any
        ) => {
            type: 'duplicate dashboard item (scenes.dashboard.dashboardLogic)'
            payload: {
                id: any
                dashboardId: any
                move: boolean
            }
        }
        duplicateDashboardItemSuccess: (
            item: any
        ) => {
            type: 'duplicate dashboard item success (scenes.dashboard.dashboardLogic)'
            payload: {
                item: any
            }
        }
        updateLayouts: (
            layouts: any
        ) => {
            type: 'update layouts (scenes.dashboard.dashboardLogic)'
            payload: {
                layouts: any
            }
        }
        updateContainerWidth: (
            containerWidth: any,
            columns: any
        ) => {
            type: 'update container width (scenes.dashboard.dashboardLogic)'
            payload: {
                containerWidth: any
                columns: any
            }
        }
        saveLayouts: () => {
            type: 'save layouts (scenes.dashboard.dashboardLogic)'
            payload: {
                value: boolean
            }
        }
        updateItemColor: (
            id: any,
            color: any
        ) => {
            type: 'update item color (scenes.dashboard.dashboardLogic)'
            payload: {
                id: any
                color: any
            }
        }
        enableDragging: () => {
            type: 'enable dragging (scenes.dashboard.dashboardLogic)'
            payload: {
                value: boolean
            }
        }
        enableWobblyDragging: () => {
            type: 'enable wobbly dragging (scenes.dashboard.dashboardLogic)'
            payload: {
                value: boolean
            }
        }
        disableDragging: () => {
            type: 'disable dragging (scenes.dashboard.dashboardLogic)'
            payload: {
                value: boolean
            }
        }
        refreshDashboardItem: (
            id: any
        ) => {
            type: 'refresh dashboard item (scenes.dashboard.dashboardLogic)'
            payload: {
                id: any
            }
        }
        loadDashboardItems: () => {
            type: 'load dashboard items (scenes.dashboard.dashboardLogic)'
            payload: any
        }
        loadDashboardItemsSuccess: (
            allItems: any[]
        ) => {
            type: 'load dashboard items success (scenes.dashboard.dashboardLogic)'
            payload: {
                allItems: any[]
            }
        }
        loadDashboardItemsFailure: (
            error: string
        ) => {
            type: 'load dashboard items failure (scenes.dashboard.dashboardLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'add new dashboard (scenes.dashboard.dashboardLogic)': 'addNewDashboard'
        'rename dashboard (scenes.dashboard.dashboardLogic)': 'renameDashboard'
        'rename dashboard item (scenes.dashboard.dashboardLogic)': 'renameDashboardItem'
        'rename dashboard item success (scenes.dashboard.dashboardLogic)': 'renameDashboardItemSuccess'
        'set is shared dashboard (scenes.dashboard.dashboardLogic)': 'setIsSharedDashboard'
        'duplicate dashboard item (scenes.dashboard.dashboardLogic)': 'duplicateDashboardItem'
        'duplicate dashboard item success (scenes.dashboard.dashboardLogic)': 'duplicateDashboardItemSuccess'
        'update layouts (scenes.dashboard.dashboardLogic)': 'updateLayouts'
        'update container width (scenes.dashboard.dashboardLogic)': 'updateContainerWidth'
        'save layouts (scenes.dashboard.dashboardLogic)': 'saveLayouts'
        'update item color (scenes.dashboard.dashboardLogic)': 'updateItemColor'
        'enable dragging (scenes.dashboard.dashboardLogic)': 'enableDragging'
        'enable wobbly dragging (scenes.dashboard.dashboardLogic)': 'enableWobblyDragging'
        'disable dragging (scenes.dashboard.dashboardLogic)': 'disableDragging'
        'refresh dashboard item (scenes.dashboard.dashboardLogic)': 'refreshDashboardItem'
        'load dashboard items (scenes.dashboard.dashboardLogic)': 'loadDashboardItems'
        'load dashboard items success (scenes.dashboard.dashboardLogic)': 'loadDashboardItemsSuccess'
        'load dashboard items failure (scenes.dashboard.dashboardLogic)': 'loadDashboardItemsFailure'
    }
    actionTypes: {
        addNewDashboard: 'add new dashboard (scenes.dashboard.dashboardLogic)'
        renameDashboard: 'rename dashboard (scenes.dashboard.dashboardLogic)'
        renameDashboardItem: 'rename dashboard item (scenes.dashboard.dashboardLogic)'
        renameDashboardItemSuccess: 'rename dashboard item success (scenes.dashboard.dashboardLogic)'
        setIsSharedDashboard: 'set is shared dashboard (scenes.dashboard.dashboardLogic)'
        duplicateDashboardItem: 'duplicate dashboard item (scenes.dashboard.dashboardLogic)'
        duplicateDashboardItemSuccess: 'duplicate dashboard item success (scenes.dashboard.dashboardLogic)'
        updateLayouts: 'update layouts (scenes.dashboard.dashboardLogic)'
        updateContainerWidth: 'update container width (scenes.dashboard.dashboardLogic)'
        saveLayouts: 'save layouts (scenes.dashboard.dashboardLogic)'
        updateItemColor: 'update item color (scenes.dashboard.dashboardLogic)'
        enableDragging: 'enable dragging (scenes.dashboard.dashboardLogic)'
        enableWobblyDragging: 'enable wobbly dragging (scenes.dashboard.dashboardLogic)'
        disableDragging: 'disable dragging (scenes.dashboard.dashboardLogic)'
        refreshDashboardItem: 'refresh dashboard item (scenes.dashboard.dashboardLogic)'
        loadDashboardItems: 'load dashboard items (scenes.dashboard.dashboardLogic)'
        loadDashboardItemsSuccess: 'load dashboard items success (scenes.dashboard.dashboardLogic)'
        loadDashboardItemsFailure: 'load dashboard items failure (scenes.dashboard.dashboardLogic)'
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
        loadDashboardItemsSuccess: (allItems: any[]) => void
        loadDashboardItemsFailure: (error: string) => void
    }
    constants: {}
    defaults: {
        allItems: any[]
        allItemsLoading: boolean
        draggingEnabled: () => 'off' | 'on'
        containerWidth: null
        columns: null
    }
    events: {
        afterMount: () => void
        beforeUnmount: () => void
    }
    key: any
    listeners: {
        addNewDashboard: ((
            payload: {
                value: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'add new dashboard (scenes.dashboard.dashboardLogic)'
                payload: {
                    value: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        setIsSharedDashboard: ((
            payload: {
                id: any
                isShared: any
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'set is shared dashboard (scenes.dashboard.dashboardLogic)'
                payload: {
                    id: any
                    isShared: any
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        renameDashboard: ((
            payload: {
                value: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'rename dashboard (scenes.dashboard.dashboardLogic)'
                payload: {
                    value: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        renameDashboardItem: ((
            payload: {
                id: any
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'rename dashboard item (scenes.dashboard.dashboardLogic)'
                payload: {
                    id: any
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        updateLayouts: ((
            payload: {
                layouts: any
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'update layouts (scenes.dashboard.dashboardLogic)'
                payload: {
                    layouts: any
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        saveLayouts: ((
            payload: {
                value: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'save layouts (scenes.dashboard.dashboardLogic)'
                payload: {
                    value: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        updateItemColor: ((
            payload: {
                id: any
                color: any
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'update item color (scenes.dashboard.dashboardLogic)'
                payload: {
                    id: any
                    color: any
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        duplicateDashboardItem: ((
            payload: {
                id: any
                dashboardId: any
                move: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'duplicate dashboard item (scenes.dashboard.dashboardLogic)'
                payload: {
                    id: any
                    dashboardId: any
                    move: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        enableWobblyDragging: ((
            payload: {
                value: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'enable wobbly dragging (scenes.dashboard.dashboardLogic)'
                payload: {
                    value: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        enableDragging: ((
            payload: {
                value: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'enable dragging (scenes.dashboard.dashboardLogic)'
                payload: {
                    value: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        disableDragging: ((
            payload: {
                value: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'disable dragging (scenes.dashboard.dashboardLogic)'
                payload: {
                    value: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        refreshDashboardItem: ((
            payload: {
                id: any
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'refresh dashboard item (scenes.dashboard.dashboardLogic)'
                payload: {
                    id: any
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
    }
    path: ['scenes', 'dashboard', 'dashboardLogic']
    pathString: 'scenes.dashboard.dashboardLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        allItems: any[]
        allItemsLoading: boolean
        draggingEnabled: () => 'off' | 'on'
        containerWidth: null
        columns: null
    }
    reducerOptions: {}
    reducers: {
        allItems: (state: any[], action: any, fullState: any) => any[]
        allItemsLoading: (state: boolean, action: any, fullState: any) => boolean
        draggingEnabled: (state: () => 'off' | 'on', action: any, fullState: any) => () => 'off' | 'on'
        containerWidth: (state: null, action: any, fullState: any) => null
        columns: (state: null, action: any, fullState: any) => null
    }
    selector: (
        state: any
    ) => {
        allItems: any[]
        allItemsLoading: boolean
        draggingEnabled: () => 'off' | 'on'
        containerWidth: null
        columns: null
    }
    selectors: {
        allItems: (state: any, props: any) => any[]
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
    sharedListeners: {}
    values: {
        allItems: any[]
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
    _isKeaWithKey: true
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
