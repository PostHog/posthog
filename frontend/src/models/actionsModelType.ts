// Auto-generated with kea-typegen. DO NOT EDIT!

export interface actionsModelType {
    key: undefined
    actionCreators: {
        loadActions: () => {
            type: 'load actions (models.actionsModel)'
            payload: any
        }
        loadActionsSuccess: (
            actions: any[]
        ) => {
            type: 'load actions success (models.actionsModel)'
            payload: {
                actions: any[]
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
        loadActions: () => void
        loadActionsSuccess: (actions: any[]) => void
        loadActionsFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: {
        actions: any[]
        actionsLoading: boolean
    }
    events: any
    path: ['models', 'actionsModel']
    pathString: 'models.actionsModel'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        actions: any[]
        actionsLoading: boolean
    }
    reducerOptions: any
    reducers: {
        actions: (state: any[], action: any, fullState: any) => any[]
        actionsLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        actions: any[]
        actionsLoading: boolean
    }
    selectors: {
        actions: (state: any, props: any) => any[]
        actionsLoading: (state: any, props: any) => boolean
        actionsGrouped: (state: any, props: any) => { label: string; options: never[] }[]
    }
    values: {
        actions: any[]
        actionsLoading: boolean
        actionsGrouped: { label: string; options: never[] }[]
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        actionsGrouped: (arg1: any) => { label: string; options: never[] }[]
    }
}
