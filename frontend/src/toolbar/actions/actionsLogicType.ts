// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic } from 'kea'

export interface actionsLogicType<ActionType> extends Logic {
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
        getActions: (_?: any) => void
        getActionsSuccess: (allActions: ActionType[]) => void
        getActionsFailure: (error: string) => void
        updateAction: ({ action }: { action: ActionType }) => void
        updateActionSuccess: (allActions: ActionType[]) => void
        updateActionFailure: (error: string) => void
        deleteAction: ({ id }: { id: number }) => void
        deleteActionSuccess: (allActions: ActionType[]) => void
        deleteActionFailure: (error: string) => void
    }
    constants: {}
    defaults: {
        allActions: ActionType[]
        allActionsLoading: boolean
    }
    events: {}
    key: undefined
    listeners: {}
    path: ['toolbar', 'actions', 'actionsLogic']
    pathString: 'toolbar.actions.actionsLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        allActions: ActionType[]
        allActionsLoading: boolean
    }
    reducerOptions: {}
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
    sharedListeners: {}
    values: {
        allActions: ActionType[]
        allActionsLoading: boolean
        sortedActions: ActionType[]
        actionsForCurrentUrl: ActionType[]
        actionCount: number
    }
    _isKea: true
    _isKeaWithKey: false
    __keaTypeGenInternalSelectorTypes: {
        sortedActions: (arg1: ActionType[]) => ActionType[]
        actionsForCurrentUrl: (arg1: ActionType[], arg2: string) => ActionType[]
        actionCount: (arg1: ActionType[]) => number
    }
}
