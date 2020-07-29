// Auto-generated with kea-typegen. DO NOT EDIT!

export interface actionsLogicType<ActionType> {
    key: any
    actionCreators: {
        getActions: (
            _?: any
        ) => {
            type: 'get actions (toolbar.actions.actionsLogic)'
            payload: any
        }
        getActionsSuccess: (
            allActions: ActionType[]
        ) => {
            type: 'get actions success (toolbar.actions.actionsLogic)'
            payload: {
                allActions: ActionType[]
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
        }: {
            action: ActionType
        }) => {
            type: 'update action (toolbar.actions.actionsLogic)'
            payload: {
                action: ActionType
            }
        }
        updateActionSuccess: (
            allActions: ActionType[]
        ) => {
            type: 'update action success (toolbar.actions.actionsLogic)'
            payload: {
                allActions: ActionType[]
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
        }: {
            id: number
        }) => {
            type: 'delete action (toolbar.actions.actionsLogic)'
            payload: {
                id: number
            }
        }
        deleteActionSuccess: (
            allActions: ActionType[]
        ) => {
            type: 'delete action success (toolbar.actions.actionsLogic)'
            payload: {
                allActions: ActionType[]
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
            _?: any
        ) => {
            type: 'get actions (toolbar.actions.actionsLogic)'
            payload: any
        }
        getActionsSuccess: (
            allActions: ActionType[]
        ) => {
            type: 'get actions success (toolbar.actions.actionsLogic)'
            payload: {
                allActions: ActionType[]
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
        }: {
            action: ActionType
        }) => {
            type: 'update action (toolbar.actions.actionsLogic)'
            payload: {
                action: ActionType
            }
        }
        updateActionSuccess: (
            allActions: ActionType[]
        ) => {
            type: 'update action success (toolbar.actions.actionsLogic)'
            payload: {
                allActions: ActionType[]
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
        }: {
            id: number
        }) => {
            type: 'delete action (toolbar.actions.actionsLogic)'
            payload: {
                id: number
            }
        }
        deleteActionSuccess: (
            allActions: ActionType[]
        ) => {
            type: 'delete action success (toolbar.actions.actionsLogic)'
            payload: {
                allActions: ActionType[]
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
        allActions: ActionType[]
        allActionsLoading: boolean
    }
    reducerOptions: any
    reducers: {
        allActions: (state: ActionType[], action: any, fullState: any) => ActionType[]
        allActionsLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        allActions: ActionType[]
        allActionsLoading: boolean
    }
    selectors: {
        allActions: (state: any, props: any) => ActionType[]
        allActionsLoading: (state: any, props: any) => boolean
        sortedActions: (state: any, props: any) => ActionType[]
        actionsForCurrentUrl: (state: any, props: any) => ActionType[]
        actionCount: (state: any, props: any) => number
    }
    values: {
        allActions: ActionType[]
        allActionsLoading: boolean
        sortedActions: ActionType[]
        actionsForCurrentUrl: ActionType[]
        actionCount: number
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        sortedActions: (arg1: ActionType[]) => ActionType[]
        actionsForCurrentUrl: (arg1: ActionType[], arg2: string) => ActionType[]
        actionCount: (arg1: ActionType[]) => number
    }
}
