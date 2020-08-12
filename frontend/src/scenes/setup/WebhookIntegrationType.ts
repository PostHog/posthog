// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic } from 'kea'

export interface logicType extends Logic {
    actionCreators: {
        setEditedWebhook: (
            webhook: any
        ) => {
            type: 'set edited webhook (scenes.setup.WebhookIntegration)'
            payload: {
                webhook: any
            }
        }
        saveWebhook: () => {
            type: 'save webhook (scenes.setup.WebhookIntegration)'
            payload: {
                value: boolean
            }
        }
        testAndSaveWebhook: () => {
            type: 'test and save webhook (scenes.setup.WebhookIntegration)'
            payload: {
                value: boolean
            }
        }
        setError: (
            error: any
        ) => {
            type: 'set error (scenes.setup.WebhookIntegration)'
            payload: {
                error: any
            }
        }
    }
    actionKeys: {
        'set edited webhook (scenes.setup.WebhookIntegration)': 'setEditedWebhook'
        'save webhook (scenes.setup.WebhookIntegration)': 'saveWebhook'
        'test and save webhook (scenes.setup.WebhookIntegration)': 'testAndSaveWebhook'
        'set error (scenes.setup.WebhookIntegration)': 'setError'
    }
    actionTypes: {
        setEditedWebhook: 'set edited webhook (scenes.setup.WebhookIntegration)'
        saveWebhook: 'save webhook (scenes.setup.WebhookIntegration)'
        testAndSaveWebhook: 'test and save webhook (scenes.setup.WebhookIntegration)'
        setError: 'set error (scenes.setup.WebhookIntegration)'
    }
    actions: {
        setEditedWebhook: (webhook: any) => void
        saveWebhook: () => void
        testAndSaveWebhook: () => void
        setError: (error: any) => void
    }
    constants: {}
    defaults: {
        editedWebhook: (state: any) => string | undefined
        isSaving: boolean
        isSaved: boolean
        error: null
    }
    events: {}
    key: undefined
    listeners: {}
    path: ['scenes', 'setup', 'WebhookIntegration']
    pathString: 'scenes.setup.WebhookIntegration'
    props: Record<string, unknown>
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
    reducerOptions: {}
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
    sharedListeners: {}
    values: {
        editedWebhook: (state: any) => string | undefined
        isSaving: boolean
        isSaved: boolean
        error: null
    }
    _isKea: true
    _isKeaWithKey: false
    __keaTypeGenInternalReducerActions: {
        __computed: (
            user: UserType,
            updateKey?: string
        ) => {
            type: 'user update success (scenes.userLogic)'
            payload: {
                user: UserType
                updateKey: string | undefined
            }
        }
    }
}
