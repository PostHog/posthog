// Auto-generated with kea-typegen. DO NOT EDIT!

export interface actionLogicType {
    key: any
    actionCreators: {
        checkIsFinished: (
            action: any
        ) => {
            type: 'check is finished (frontend.src.scenes.actions.Action)'
            payload: { action: any }
        }
        setPollTimeout: (
            pollTimeout: any
        ) => {
            type: 'set poll timeout (frontend.src.scenes.actions.Action)'
            payload: { pollTimeout: any }
        }
        setIsComplete: (
            isComplete: any
        ) => {
            type: 'set is complete (frontend.src.scenes.actions.Action)'
            payload: { isComplete: any }
        }
        loadAction: () => {
            type: 'load action (frontend.src.scenes.actions.Action)'
            payload: any
        }
        loadActionSuccess: (
            action: any
        ) => {
            type: 'load action success (frontend.src.scenes.actions.Action)'
            payload: {
                action: any
            }
        }
        loadActionFailure: (
            error: string
        ) => {
            type: 'load action failure (frontend.src.scenes.actions.Action)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'check is finished (frontend.src.scenes.actions.Action)': 'checkIsFinished'
        'set poll timeout (frontend.src.scenes.actions.Action)': 'setPollTimeout'
        'set is complete (frontend.src.scenes.actions.Action)': 'setIsComplete'
        'load action (frontend.src.scenes.actions.Action)': 'loadAction'
        'load action success (frontend.src.scenes.actions.Action)': 'loadActionSuccess'
        'load action failure (frontend.src.scenes.actions.Action)': 'loadActionFailure'
    }
    actionTypes: {
        checkIsFinished: 'check is finished (frontend.src.scenes.actions.Action)'
        setPollTimeout: 'set poll timeout (frontend.src.scenes.actions.Action)'
        setIsComplete: 'set is complete (frontend.src.scenes.actions.Action)'
        loadAction: 'load action (frontend.src.scenes.actions.Action)'
        loadActionSuccess: 'load action success (frontend.src.scenes.actions.Action)'
        loadActionFailure: 'load action failure (frontend.src.scenes.actions.Action)'
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
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'actions', 'Action']
    pathString: 'frontend.src.scenes.actions.Action'
    propTypes: any
    props: Record<string, any>
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
