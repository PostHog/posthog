// Auto-generated with kea-typegen. DO NOT EDIT!

export interface teamLogicType {
    key: any
    actionCreators: {
        loadUsers: () => {
            type: 'load users (frontend.src.scenes.team.teamLogic)'
            payload: any
        }
        loadUsersSuccess: (users: {}) => {
            type: 'load users success (frontend.src.scenes.team.teamLogic)'
            payload: {
                users: {}
            }
        }
        loadUsersFailure: (
            error: string
        ) => {
            type: 'load users failure (frontend.src.scenes.team.teamLogic)'
            payload: {
                error: string
            }
        }
        deleteUser: (
            user: any
        ) => {
            type: 'delete user (frontend.src.scenes.team.teamLogic)'
            payload: any
        }
        deleteUserSuccess: (users: {}) => {
            type: 'delete user success (frontend.src.scenes.team.teamLogic)'
            payload: {
                users: {}
            }
        }
        deleteUserFailure: (
            error: string
        ) => {
            type: 'delete user failure (frontend.src.scenes.team.teamLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'load users (frontend.src.scenes.team.teamLogic)': 'loadUsers'
        'load users success (frontend.src.scenes.team.teamLogic)': 'loadUsersSuccess'
        'load users failure (frontend.src.scenes.team.teamLogic)': 'loadUsersFailure'
        'delete user (frontend.src.scenes.team.teamLogic)': 'deleteUser'
        'delete user success (frontend.src.scenes.team.teamLogic)': 'deleteUserSuccess'
        'delete user failure (frontend.src.scenes.team.teamLogic)': 'deleteUserFailure'
    }
    actionTypes: {
        loadUsers: 'load users (frontend.src.scenes.team.teamLogic)'
        loadUsersSuccess: 'load users success (frontend.src.scenes.team.teamLogic)'
        loadUsersFailure: 'load users failure (frontend.src.scenes.team.teamLogic)'
        deleteUser: 'delete user (frontend.src.scenes.team.teamLogic)'
        deleteUserSuccess: 'delete user success (frontend.src.scenes.team.teamLogic)'
        deleteUserFailure: 'delete user failure (frontend.src.scenes.team.teamLogic)'
    }
    actions: {
        loadUsers: () => void
        loadUsersSuccess: (users: {}) => void
        loadUsersFailure: (error: string) => void
        deleteUser: (user: any) => void
        deleteUserSuccess: (users: {}) => void
        deleteUserFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'team', 'teamLogic']
    pathString: 'frontend.src.scenes.team.teamLogic'
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
