// Auto-generated with kea-typegen. DO NOT EDIT!

export interface teamLogicType {
    key: any
    actionCreators: {
        loadUsers: () => {
            type: 'load users (scenes.team.teamLogic)'
            payload: any
        }
        loadUsersSuccess: (users: {}) => {
            type: 'load users success (scenes.team.teamLogic)'
            payload: {
                users: {}
            }
        }
        loadUsersFailure: (
            error: string
        ) => {
            type: 'load users failure (scenes.team.teamLogic)'
            payload: {
                error: string
            }
        }
        deleteUser: (
            user: any
        ) => {
            type: 'delete user (scenes.team.teamLogic)'
            payload: any
        }
        deleteUserSuccess: (users: {}) => {
            type: 'delete user success (scenes.team.teamLogic)'
            payload: {
                users: {}
            }
        }
        deleteUserFailure: (
            error: string
        ) => {
            type: 'delete user failure (scenes.team.teamLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'load users (scenes.team.teamLogic)': 'loadUsers'
        'load users success (scenes.team.teamLogic)': 'loadUsersSuccess'
        'load users failure (scenes.team.teamLogic)': 'loadUsersFailure'
        'delete user (scenes.team.teamLogic)': 'deleteUser'
        'delete user success (scenes.team.teamLogic)': 'deleteUserSuccess'
        'delete user failure (scenes.team.teamLogic)': 'deleteUserFailure'
    }
    actionTypes: {
        loadUsers: 'load users (scenes.team.teamLogic)'
        loadUsersSuccess: 'load users success (scenes.team.teamLogic)'
        loadUsersFailure: 'load users failure (scenes.team.teamLogic)'
        deleteUser: 'delete user (scenes.team.teamLogic)'
        deleteUserSuccess: 'delete user success (scenes.team.teamLogic)'
        deleteUserFailure: 'delete user failure (scenes.team.teamLogic)'
    }
    actions: {
        loadUsers: () => {
            type: 'load users (scenes.team.teamLogic)'
            payload: any
        }
        loadUsersSuccess: (users: {}) => {
            type: 'load users success (scenes.team.teamLogic)'
            payload: {
                users: {}
            }
        }
        loadUsersFailure: (
            error: string
        ) => {
            type: 'load users failure (scenes.team.teamLogic)'
            payload: {
                error: string
            }
        }
        deleteUser: (
            user: any
        ) => {
            type: 'delete user (scenes.team.teamLogic)'
            payload: any
        }
        deleteUserSuccess: (users: {}) => {
            type: 'delete user success (scenes.team.teamLogic)'
            payload: {
                users: {}
            }
        }
        deleteUserFailure: (
            error: string
        ) => {
            type: 'delete user failure (scenes.team.teamLogic)'
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
    path: ['scenes', 'team', 'teamLogic']
    pathString: 'scenes.team.teamLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        users: {}
        usersLoading: boolean
    }
    reducerOptions: any
    reducers: {
        users: (state: {}, action: any, fullState: any) => {}
        usersLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        users: {}
        usersLoading: boolean
    }
    selectors: {
        users: (state: any, props: any) => {}
        usersLoading: (state: any, props: any) => boolean
    }
    values: {
        users: {}
        usersLoading: boolean
    }
    _isKea: true
}
