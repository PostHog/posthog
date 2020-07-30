// Auto-generated with kea-typegen. DO NOT EDIT!

export interface logicType {
    key: any
    actionCreators: {
        setEditedWebhook: (
            webhook: any
        ) => {
            type: 'set edited webhook (frontend.src.scenes.setup.SlackIntegration)'
            payload: { webhook: any }
        }
        saveWebhook: () => {
            type: 'save webhook (frontend.src.scenes.setup.SlackIntegration)'
            payload: {
                value: boolean
            }
        }
        testAndSaveWebhook: () => {
            type: 'test and save webhook (frontend.src.scenes.setup.SlackIntegration)'
            payload: {
                value: boolean
            }
        }
        setError: (
            error: any
        ) => {
            type: 'set error (frontend.src.scenes.setup.SlackIntegration)'
            payload: { error: any }
        }
    }
    actionKeys: {
        'set edited webhook (frontend.src.scenes.setup.SlackIntegration)': 'setEditedWebhook'
        'save webhook (frontend.src.scenes.setup.SlackIntegration)': 'saveWebhook'
        'test and save webhook (frontend.src.scenes.setup.SlackIntegration)': 'testAndSaveWebhook'
        'set error (frontend.src.scenes.setup.SlackIntegration)': 'setError'
    }
    actionTypes: {
        setEditedWebhook: 'set edited webhook (frontend.src.scenes.setup.SlackIntegration)'
        saveWebhook: 'save webhook (frontend.src.scenes.setup.SlackIntegration)'
        testAndSaveWebhook: 'test and save webhook (frontend.src.scenes.setup.SlackIntegration)'
        setError: 'set error (frontend.src.scenes.setup.SlackIntegration)'
    }
    actions: {
        setEditedWebhook: (webhook: any) => void
        saveWebhook: () => void
        testAndSaveWebhook: () => void
        setError: (error: any) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'setup', 'SlackIntegration']
    pathString: 'frontend.src.scenes.setup.SlackIntegration'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        editedWebhook: (state: any) => string | undefined
        isSaving: boolean
        isSaved: boolean
        error: null
    }
    reducerOptions: any
    reducers: {
        editedWebhook: (
            state: (state: any) => string | undefined,
            action: any,
            fullState: any
        ) => (state: any) => string | undefined
        isSaving: (state: boolean, action: any, fullState: any) => boolean
        isSaved: (state: boolean, action: any, fullState: any) => boolean
        error: (state: null, action: any, fullState: any) => null
    }
    selector: (
        state: any
    ) => {
        editedWebhook: (state: any) => string | undefined
        isSaving: boolean
        isSaved: boolean
        error: null
    }
    selectors: {
        editedWebhook: (state: any, props: any) => (state: any) => string | undefined
        isSaving: (state: any, props: any) => boolean
        isSaved: (state: any, props: any) => boolean
        error: (state: any, props: any) => null
    }
    values: {
        editedWebhook: (state: any) => string | undefined
        isSaving: boolean
        isSaved: boolean
        error: null
    }
    _isKea: true
    __keaTypeGenInternalReducerActions: {
        __computed: (
            user: UserType,
            updateKey?: string
        ) => {
            type: 'user update success (frontend.src.scenes.userLogic)'
            payload: {
                user: UserType
                updateKey: string | undefined
            }
        }
    }
}
