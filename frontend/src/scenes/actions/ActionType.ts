// Auto-generated with kea-typegen. DO NOT EDIT!

export interface actionLogicType {
    key: unknown
    actionCreators: {
        checkIsFinished: (
            action: any
        ) => {
            type: 'check is finished (scenes.actions.Action)'
            payload: { action: any }
        }
        setPollTimeout: (
            pollTimeout: any
        ) => {
            type: 'set poll timeout (scenes.actions.Action)'
            payload: { pollTimeout: any }
        }
        setIsComplete: (
            isComplete: any
        ) => {
            type: 'set is complete (scenes.actions.Action)'
            payload: { isComplete: any }
        }
        loadAction: () => {
            type: 'load action (scenes.actions.Action)'
            payload: any
        }
        loadActionSuccess: (
            action: any
        ) => {
            type: 'load action success (scenes.actions.Action)'
            payload: {
                action: any
            }
        }
        loadActionFailure: (
            error: string
        ) => {
            type: 'load action failure (scenes.actions.Action)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'check is finished (scenes.actions.Action)': 'checkIsFinished'
        'set poll timeout (scenes.actions.Action)': 'setPollTimeout'
        'set is complete (scenes.actions.Action)': 'setIsComplete'
        'load action (scenes.actions.Action)': 'loadAction'
        'load action success (scenes.actions.Action)': 'loadActionSuccess'
        'load action failure (scenes.actions.Action)': 'loadActionFailure'
    }
    actionTypes: {
        checkIsFinished: 'check is finished (scenes.actions.Action)'
        setPollTimeout: 'set poll timeout (scenes.actions.Action)'
        setIsComplete: 'set is complete (scenes.actions.Action)'
        loadAction: 'load action (scenes.actions.Action)'
        loadActionSuccess: 'load action success (scenes.actions.Action)'
        loadActionFailure: 'load action failure (scenes.actions.Action)'
    }
    actions: {
        checkIsFinished: (action: any) => void
        setPollTimeout: (pollTimeout: any) => void
        setIsComplete: (isComplete: any) => void
        loadAction: () => void
        loadActionSuccess: (action: any) => void
        loadActionFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: {
        pollTimeout: null
        isComplete: boolean
        action: any
        actionLoading: boolean
    }
    events: any
    path: ['scenes', 'actions', 'Action']
    pathString: 'scenes.actions.Action'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        pollTimeout: null
        isComplete: boolean
        action: any
        actionLoading: boolean
    }
    reducerOptions: any
    reducers: {
        pollTimeout: (state: null, action: any, fullState: any) => null
        isComplete: (state: boolean, action: any, fullState: any) => boolean
        action: (state: any, action: any, fullState: any) => any
        actionLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        pollTimeout: null
        isComplete: boolean
        action: any
        actionLoading: boolean
    }
    selectors: {
        pollTimeout: (state: any, props: any) => null
        isComplete: (state: any, props: any) => boolean
        action: (state: any, props: any) => any
        actionLoading: (state: any, props: any) => boolean
    }
    values: {
        pollTimeout: null
        isComplete: boolean
        action: any
        actionLoading: boolean
    }
    _isKea: true
}
