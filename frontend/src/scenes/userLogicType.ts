// Auto-generated with kea-typegen. DO NOT EDIT!

export interface userLogicType<UserType, EventProperty> {
    key: any
    actionCreators: {
        loadUser: () => {
            type: 'load user (scenes.userLogic)'
            payload: {
                value: boolean
            }
        }
        setUser: (
            user: UserType | null,
            updateKey?: string
        ) => {
            type: 'set user (scenes.userLogic)'
            payload: { user: UserType | null; updateKey: string | undefined }
        }
        userUpdateRequest: (
            update: Partial<UserType>,
            updateKey?: string
        ) => {
            type: 'user update request (scenes.userLogic)'
            payload: { update: Partial<UserType>; updateKey: string | undefined }
        }
        userUpdateSuccess: (
            user: UserType,
            updateKey?: string
        ) => {
            type: 'user update success (scenes.userLogic)'
            payload: { user: UserType; updateKey: string | undefined }
        }
        userUpdateFailure: (
            error: string,
            updateKey?: string
        ) => {
            type: 'user update failure (scenes.userLogic)'
            payload: { updateKey: string | undefined; error: string }
        }
    }
    actionKeys: {
        'load user (scenes.userLogic)': 'loadUser'
        'set user (scenes.userLogic)': 'setUser'
        'user update request (scenes.userLogic)': 'userUpdateRequest'
        'user update success (scenes.userLogic)': 'userUpdateSuccess'
        'user update failure (scenes.userLogic)': 'userUpdateFailure'
    }
    actionTypes: {
        loadUser: 'load user (scenes.userLogic)'
        setUser: 'set user (scenes.userLogic)'
        userUpdateRequest: 'user update request (scenes.userLogic)'
        userUpdateSuccess: 'user update success (scenes.userLogic)'
        userUpdateFailure: 'user update failure (scenes.userLogic)'
    }
    actions: {
        loadUser: () => {
            type: 'load user (scenes.userLogic)'
            payload: {
                value: boolean
            }
        }
        setUser: (
            user: UserType | null,
            updateKey?: string
        ) => {
            type: 'set user (scenes.userLogic)'
            payload: { user: UserType | null; updateKey: string | undefined }
        }
        userUpdateRequest: (
            update: Partial<UserType>,
            updateKey?: string
        ) => {
            type: 'user update request (scenes.userLogic)'
            payload: { update: Partial<UserType>; updateKey: string | undefined }
        }
        userUpdateSuccess: (
            user: UserType,
            updateKey?: string
        ) => {
            type: 'user update success (scenes.userLogic)'
            payload: { user: UserType; updateKey: string | undefined }
        }
        userUpdateFailure: (
            error: string,
            updateKey?: string
        ) => {
            type: 'user update failure (scenes.userLogic)'
            payload: { updateKey: string | undefined; error: string }
        }
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['scenes', 'userLogic']
    pathString: 'scenes.userLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        user: UserType | null
    }
    reducerOptions: any
    reducers: {
        user: (state: UserType | null, action: any, fullState: any) => UserType | null
    }
    selector: (
        state: any
    ) => {
        user: UserType | null
    }
    selectors: {
        user: (state: any, props: any) => UserType | null
        eventProperties: (state: any, props: any) => EventProperty[]
        eventNames: (state: any, props: any) => string[]
        customEventNames: (state: any, props: any) => string[]
        eventNamesGrouped: (state: any, props: any) => { label: string; options: EventProperty[] }[]
    }
    values: {
        user: UserType | null
        eventProperties: EventProperty[]
        eventNames: string[]
        customEventNames: string[]
        eventNamesGrouped: { label: string; options: EventProperty[] }[]
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        eventProperties: (arg1: UserType | null) => EventProperty[]
        eventNames: (arg1: UserType | null) => string[]
        customEventNames: (arg1: UserType | null) => string[]
        eventNamesGrouped: (arg1: UserType | null) => { label: string; options: EventProperty[] }[]
    }
}
