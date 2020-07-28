// Auto-generated with kea-typegen. DO NOT EDIT!

export interface actionsLogicType {
    key: any
    actionCreators: {
        getActions: (
            _: any
        ) => {
            type: 'get actions (toolbar.actions.actionsLogic)'
            payload: any
        }
        getActionsSuccess: (
            allActions: never[]
        ) => {
            type: 'get actions success (toolbar.actions.actionsLogic)'
            payload: {
                allActions: never[]
            }
        }
        getActionsFailure: (
            error: string
        ) => {
            type: 'get actions failure (toolbar.actions.actionsLogic)'
            payload: {
                error: string
            }
        }
        updateAction: ({
            action,
        }: any) => {
            type: 'update action (toolbar.actions.actionsLogic)'
            payload: any
        }
        updateActionSuccess: (
            allActions: never[]
        ) => {
            type: 'update action success (toolbar.actions.actionsLogic)'
            payload: {
                allActions: never[]
            }
        }
        updateActionFailure: (
            error: string
        ) => {
            type: 'update action failure (toolbar.actions.actionsLogic)'
            payload: {
                error: string
            }
        }
        deleteAction: ({
            id,
        }: any) => {
            type: 'delete action (toolbar.actions.actionsLogic)'
            payload: any
        }
        deleteActionSuccess: (
            allActions: never[]
        ) => {
            type: 'delete action success (toolbar.actions.actionsLogic)'
            payload: {
                allActions: never[]
            }
        }
        deleteActionFailure: (
            error: string
        ) => {
            type: 'delete action failure (toolbar.actions.actionsLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'get actions (toolbar.actions.actionsLogic)': 'getActions'
        'get actions success (toolbar.actions.actionsLogic)': 'getActionsSuccess'
        'get actions failure (toolbar.actions.actionsLogic)': 'getActionsFailure'
        'update action (toolbar.actions.actionsLogic)': 'updateAction'
        'update action success (toolbar.actions.actionsLogic)': 'updateActionSuccess'
        'update action failure (toolbar.actions.actionsLogic)': 'updateActionFailure'
        'delete action (toolbar.actions.actionsLogic)': 'deleteAction'
        'delete action success (toolbar.actions.actionsLogic)': 'deleteActionSuccess'
        'delete action failure (toolbar.actions.actionsLogic)': 'deleteActionFailure'
    }
    actionTypes: {
        getActions: 'get actions (toolbar.actions.actionsLogic)'
        getActionsSuccess: 'get actions success (toolbar.actions.actionsLogic)'
        getActionsFailure: 'get actions failure (toolbar.actions.actionsLogic)'
        updateAction: 'update action (toolbar.actions.actionsLogic)'
        updateActionSuccess: 'update action success (toolbar.actions.actionsLogic)'
        updateActionFailure: 'update action failure (toolbar.actions.actionsLogic)'
        deleteAction: 'delete action (toolbar.actions.actionsLogic)'
        deleteActionSuccess: 'delete action success (toolbar.actions.actionsLogic)'
        deleteActionFailure: 'delete action failure (toolbar.actions.actionsLogic)'
    }
    actions: {
        getActions: (
            _: any
        ) => {
            type: 'get actions (toolbar.actions.actionsLogic)'
            payload: any
        }
        getActionsSuccess: (
            allActions: never[]
        ) => {
            type: 'get actions success (toolbar.actions.actionsLogic)'
            payload: {
                allActions: never[]
            }
        }
        getActionsFailure: (
            error: string
        ) => {
            type: 'get actions failure (toolbar.actions.actionsLogic)'
            payload: {
                error: string
            }
        }
        updateAction: ({
            action,
        }: any) => {
            type: 'update action (toolbar.actions.actionsLogic)'
            payload: any
        }
        updateActionSuccess: (
            allActions: never[]
        ) => {
            type: 'update action success (toolbar.actions.actionsLogic)'
            payload: {
                allActions: never[]
            }
        }
        updateActionFailure: (
            error: string
        ) => {
            type: 'update action failure (toolbar.actions.actionsLogic)'
            payload: {
                error: string
            }
        }
        deleteAction: ({
            id,
        }: any) => {
            type: 'delete action (toolbar.actions.actionsLogic)'
            payload: any
        }
        deleteActionSuccess: (
            allActions: never[]
        ) => {
            type: 'delete action success (toolbar.actions.actionsLogic)'
            payload: {
                allActions: never[]
            }
        }
        deleteActionFailure: (
            error: string
        ) => {
            type: 'delete action failure (toolbar.actions.actionsLogic)'
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
    path: ['toolbar', 'actions', 'actionsLogic']
    pathString: 'toolbar.actions.actionsLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        allActions: never[]
        allActionsLoading: boolean
    }
    reducerOptions: any
    reducers: {
        allActions: (state: never[], action: any, fullState: any) => never[]
        allActionsLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        allActions: never[]
        allActionsLoading: boolean
    }
    selectors: {
        allActions: (state: any, props: any) => never[]
        allActionsLoading: (state: any, props: any) => boolean
        sortedActions: (state: any, props: any) => any[]
        actionsForCurrentUrl: (state: any, props: any) => any
        actionCount: (state: any, props: any) => any
    }
    values: {
        allActions: never[]
        allActionsLoading: boolean
        sortedActions: any[]
        actionsForCurrentUrl: any
        actionCount: any
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        sortedActions: (arg1: any) => any[]
        actionsForCurrentUrl: (arg1: any, arg2: any) => any
        actionCount: (arg1: any) => any
    }
}
