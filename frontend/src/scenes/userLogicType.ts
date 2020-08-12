// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic, BreakPointFunction } from 'kea'

export interface userLogicType<UserType, EventProperty> extends Logic {
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
            payload: {
                user: UserType | null
                updateKey: string | undefined
            }
        }
        userUpdateRequest: (
            update: Partial<UserType>,
            updateKey?: string
        ) => {
            type: 'user update request (scenes.userLogic)'
            payload: {
                update: Partial<UserType>
                updateKey: string | undefined
            }
        }
        userUpdateSuccess: (
            user: UserType,
            updateKey?: string
        ) => {
            type: 'user update success (scenes.userLogic)'
            payload: {
                user: UserType
                updateKey: string | undefined
            }
        }
        userUpdateFailure: (
            error: string,
            updateKey?: string
        ) => {
            type: 'user update failure (scenes.userLogic)'
            payload: {
                updateKey: string | undefined
                error: string
            }
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
        loadUser: () => void
        setUser: (user: UserType | null, updateKey?: string) => void
        userUpdateRequest: (update: Partial<UserType>, updateKey?: string) => void
        userUpdateSuccess: (user: UserType, updateKey?: string) => void
        userUpdateFailure: (error: string, updateKey?: string) => void
    }
    constants: {}
    defaults: {
        user: UserType | null
    }
    events: {
        afterMount: () => void
    }
    key: undefined
    listeners: {
        loadUser: ((
            payload: {
                value: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'load user (scenes.userLogic)'
                payload: {
                    value: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        userUpdateRequest: ((
            payload: {
                update: Partial<UserType>
                updateKey: string | undefined
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'user update request (scenes.userLogic)'
                payload: {
                    update: Partial<UserType>
                    updateKey: string | undefined
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
    }
    path: ['scenes', 'userLogic']
    pathString: 'scenes.userLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        user: UserType | null
    }
    reducerOptions: {}
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
    sharedListeners: {}
    values: {
        user: UserType | null
        eventProperties: EventProperty[]
        eventNames: string[]
        customEventNames: string[]
        eventNamesGrouped: { label: string; options: EventProperty[] }[]
    }
    _isKea: true
    _isKeaWithKey: false
    __keaTypeGenInternalSelectorTypes: {
        eventProperties: (arg1: UserType | null) => EventProperty[]
        eventNames: (arg1: UserType | null) => string[]
        customEventNames: (arg1: UserType | null) => string[]
        eventNamesGrouped: (arg1: UserType | null) => { label: string; options: EventProperty[] }[]
    }
}
