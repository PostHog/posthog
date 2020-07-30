// Auto-generated with kea-typegen. DO NOT EDIT!

export interface actionsModelType {
    key: any
    actionCreators: {
        loadActions: () => {
            type: 'load actions (frontend.src.models.actionsModel)'
            payload: any
        }
        loadActionsSuccess: (
            actions: never[]
        ) => {
            type: 'load actions success (frontend.src.models.actionsModel)'
            payload: {
                actions: never[]
            }
        }
        loadActionsFailure: (
            error: string
        ) => {
            type: 'load actions failure (frontend.src.models.actionsModel)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'load actions (frontend.src.models.actionsModel)': 'loadActions'
        'load actions success (frontend.src.models.actionsModel)': 'loadActionsSuccess'
        'load actions failure (frontend.src.models.actionsModel)': 'loadActionsFailure'
    }
    actionTypes: {
        loadActions: 'load actions (frontend.src.models.actionsModel)'
        loadActionsSuccess: 'load actions success (frontend.src.models.actionsModel)'
        loadActionsFailure: 'load actions failure (frontend.src.models.actionsModel)'
    }
    actions: {
        loadActions: () => void
        loadActionsSuccess: (actions: never[]) => void
        loadActionsFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'models', 'actionsModel']
    pathString: 'frontend.src.models.actionsModel'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        actions: never[]
        actionsLoading: boolean
    }
    reducerOptions: any
    reducers: {
        actions: (state: never[], action: any, fullState: any) => never[]
        actionsLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        actions: never[]
        actionsLoading: boolean
    }
    selectors: {
        actions: (state: any, props: any) => never[]
        actionsLoading: (state: any, props: any) => boolean
        actionsGrouped: (state: any, props: any) => { label: string; options: never[] }[]
    }
    values: {
        actions: never[]
        actionsLoading: boolean
        actionsGrouped: { label: string; options: never[] }[]
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        actionsGrouped: (arg1: any) => { label: string; options: never[] }[]
    }
}
