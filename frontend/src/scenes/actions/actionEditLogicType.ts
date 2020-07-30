// Auto-generated with kea-typegen. DO NOT EDIT!

export interface actionEditLogicType {
    key: any
    actionCreators: {
        saveAction: () => {
            type: 'save action (scenes.actions.actionEditLogic)'
            payload: {
                value: boolean
            }
        }
        setAction: (
            action: any
        ) => {
            type: 'set action (scenes.actions.actionEditLogic)'
            payload: { action: any }
        }
        setCreateNew: (
            createNew: any
        ) => {
            type: 'set create new (scenes.actions.actionEditLogic)'
            payload: { createNew: any }
        }
        actionAlreadyExists: (
            actionId: any
        ) => {
            type: 'action already exists (scenes.actions.actionEditLogic)'
            payload: { actionId: any }
        }
        loadAction: () => {
            type: 'load action (scenes.actions.actionEditLogic)'
            payload: any
        }
        loadActionSuccess: (
            action: any
        ) => {
            type: 'load action success (scenes.actions.actionEditLogic)'
            payload: {
                action: any
            }
        }
        loadActionFailure: (
            error: string
        ) => {
            type: 'load action failure (scenes.actions.actionEditLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'save action (scenes.actions.actionEditLogic)': 'saveAction'
        'set action (scenes.actions.actionEditLogic)': 'setAction'
        'set create new (scenes.actions.actionEditLogic)': 'setCreateNew'
        'action already exists (scenes.actions.actionEditLogic)': 'actionAlreadyExists'
        'load action (scenes.actions.actionEditLogic)': 'loadAction'
        'load action success (scenes.actions.actionEditLogic)': 'loadActionSuccess'
        'load action failure (scenes.actions.actionEditLogic)': 'loadActionFailure'
    }
    actionTypes: {
        saveAction: 'save action (scenes.actions.actionEditLogic)'
        setAction: 'set action (scenes.actions.actionEditLogic)'
        setCreateNew: 'set create new (scenes.actions.actionEditLogic)'
        actionAlreadyExists: 'action already exists (scenes.actions.actionEditLogic)'
        loadAction: 'load action (scenes.actions.actionEditLogic)'
        loadActionSuccess: 'load action success (scenes.actions.actionEditLogic)'
        loadActionFailure: 'load action failure (scenes.actions.actionEditLogic)'
    }
    actions: {
        saveAction: () => void
        setAction: (action: any) => void
        setCreateNew: (createNew: any) => void
        actionAlreadyExists: (actionId: any) => void
        loadAction: () => void
        loadActionSuccess: (action: any) => void
        loadActionFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['scenes', 'actions', 'actionEditLogic']
    pathString: 'scenes.actions.actionEditLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        action: any
        actionLoading: boolean
        errorActionId: null
        createNew: boolean
    }
    reducerOptions: any
    reducers: {
        action: (state: any, action: any, fullState: any) => any
        actionLoading: (state: boolean, action: any, fullState: any) => boolean
        errorActionId: (state: null, action: any, fullState: any) => null
        createNew: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        action: any
        actionLoading: boolean
        errorActionId: null
        createNew: boolean
    }
    selectors: {
        action: (state: any, props: any) => any
        actionLoading: (state: any, props: any) => boolean
        errorActionId: (state: any, props: any) => null
        createNew: (state: any, props: any) => boolean
    }
    values: {
        action: any
        actionLoading: boolean
        errorActionId: null
        createNew: boolean
    }
    _isKea: true
}
