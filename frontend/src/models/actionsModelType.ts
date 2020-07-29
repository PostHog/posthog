// Auto-generated with kea-typegen. DO NOT EDIT!

export interface actionsModelType {
    key: any
    actionCreators: {
        loadActions: () => {
            type: 'load actions (models.actionsModel)'
            payload: any
        }
        loadActionsSuccess: (
            actions: undefined[]
        ) => {
            type: 'load actions success (models.actionsModel)'
            payload: {
                actions: undefined[]
            }
        }
        loadActionsFailure: (
            error: string
        ) => {
            type: 'load actions failure (models.actionsModel)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'load actions (models.actionsModel)': 'loadActions'
        'load actions success (models.actionsModel)': 'loadActionsSuccess'
        'load actions failure (models.actionsModel)': 'loadActionsFailure'
    }
    actionTypes: {
        loadActions: 'load actions (models.actionsModel)'
        loadActionsSuccess: 'load actions success (models.actionsModel)'
        loadActionsFailure: 'load actions failure (models.actionsModel)'
    }
    actions: {
        loadActions: () => {
            type: 'load actions (models.actionsModel)'
            payload: any
        }
        loadActionsSuccess: (
            actions: undefined[]
        ) => {
            type: 'load actions success (models.actionsModel)'
            payload: {
                actions: undefined[]
            }
        }
        loadActionsFailure: (
            error: string
        ) => {
            type: 'load actions failure (models.actionsModel)'
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
    path: ['models', 'actionsModel']
    pathString: 'models.actionsModel'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        actions: undefined[]
        actionsLoading: boolean
    }
    reducerOptions: any
    reducers: {
        actions: (state: undefined[], action: any, fullState: any) => undefined[]
        actionsLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        actions: undefined[]
        actionsLoading: boolean
    }
    selectors: {
        actions: (state: any, props: any) => undefined[]
        actionsLoading: (state: any, props: any) => boolean
        actionsGrouped: (state: any, props: any) => { label: string; options: any[] }[]
    }
    values: {
        actions: undefined[]
        actionsLoading: boolean
        actionsGrouped: { label: string; options: any[] }[]
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        actionsGrouped: (arg1: any) => { label: string; options: any[] }[]
    }
}
