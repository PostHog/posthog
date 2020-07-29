// Auto-generated with kea-typegen. DO NOT EDIT!

export interface sessionsTableLogicType {
    key: any
    actionCreators: {
        loadSessions: (
            selectedDate: any
        ) => {
            type: 'load sessions (scenes.sessions.sessionsTableLogic)'
            payload: any
        }
        loadSessionsSuccess: (
            sessions: undefined[]
        ) => {
            type: 'load sessions success (scenes.sessions.sessionsTableLogic)'
            payload: {
                sessions: undefined[]
            }
        }
        loadSessionsFailure: (
            error: string
        ) => {
            type: 'load sessions failure (scenes.sessions.sessionsTableLogic)'
            payload: {
                error: string
            }
        }
        setOffset: (
            offset: any
        ) => {
            type: 'set offset (scenes.sessions.sessionsTableLogic)'
            payload: { offset: any }
        }
        fetchNextSessions: () => {
            type: 'fetch next sessions (scenes.sessions.sessionsTableLogic)'
            payload: {
                value: boolean
            }
        }
        appendNewSessions: (
            sessions: any
        ) => {
            type: 'append new sessions (scenes.sessions.sessionsTableLogic)'
            payload: { sessions: any }
        }
        dateChanged: (
            date: any
        ) => {
            type: 'date changed (scenes.sessions.sessionsTableLogic)'
            payload: { date: any }
        }
        setDate: (
            date: any
        ) => {
            type: 'set date (scenes.sessions.sessionsTableLogic)'
            payload: { date: any }
        }
    }
    actionKeys: {
        'load sessions (scenes.sessions.sessionsTableLogic)': 'loadSessions'
        'load sessions success (scenes.sessions.sessionsTableLogic)': 'loadSessionsSuccess'
        'load sessions failure (scenes.sessions.sessionsTableLogic)': 'loadSessionsFailure'
        'set offset (scenes.sessions.sessionsTableLogic)': 'setOffset'
        'fetch next sessions (scenes.sessions.sessionsTableLogic)': 'fetchNextSessions'
        'append new sessions (scenes.sessions.sessionsTableLogic)': 'appendNewSessions'
        'date changed (scenes.sessions.sessionsTableLogic)': 'dateChanged'
        'set date (scenes.sessions.sessionsTableLogic)': 'setDate'
    }
    actionTypes: {
        loadSessions: 'load sessions (scenes.sessions.sessionsTableLogic)'
        loadSessionsSuccess: 'load sessions success (scenes.sessions.sessionsTableLogic)'
        loadSessionsFailure: 'load sessions failure (scenes.sessions.sessionsTableLogic)'
        setOffset: 'set offset (scenes.sessions.sessionsTableLogic)'
        fetchNextSessions: 'fetch next sessions (scenes.sessions.sessionsTableLogic)'
        appendNewSessions: 'append new sessions (scenes.sessions.sessionsTableLogic)'
        dateChanged: 'date changed (scenes.sessions.sessionsTableLogic)'
        setDate: 'set date (scenes.sessions.sessionsTableLogic)'
    }
    actions: {
        loadSessions: (
            selectedDate: any
        ) => {
            type: 'load sessions (scenes.sessions.sessionsTableLogic)'
            payload: any
        }
        loadSessionsSuccess: (
            sessions: undefined[]
        ) => {
            type: 'load sessions success (scenes.sessions.sessionsTableLogic)'
            payload: {
                sessions: undefined[]
            }
        }
        loadSessionsFailure: (
            error: string
        ) => {
            type: 'load sessions failure (scenes.sessions.sessionsTableLogic)'
            payload: {
                error: string
            }
        }
        setOffset: (
            offset: any
        ) => {
            type: 'set offset (scenes.sessions.sessionsTableLogic)'
            payload: { offset: any }
        }
        fetchNextSessions: () => {
            type: 'fetch next sessions (scenes.sessions.sessionsTableLogic)'
            payload: {
                value: boolean
            }
        }
        appendNewSessions: (
            sessions: any
        ) => {
            type: 'append new sessions (scenes.sessions.sessionsTableLogic)'
            payload: { sessions: any }
        }
        dateChanged: (
            date: any
        ) => {
            type: 'date changed (scenes.sessions.sessionsTableLogic)'
            payload: { date: any }
        }
        setDate: (
            date: any
        ) => {
            type: 'set date (scenes.sessions.sessionsTableLogic)'
            payload: { date: any }
        }
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['scenes', 'sessions', 'sessionsTableLogic']
    pathString: 'scenes.sessions.sessionsTableLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        sessions: undefined[]
        sessionsLoading: boolean
        isLoadingNext: boolean
        offset: null
        selectedDate: Moment
    }
    reducerOptions: any
    reducers: {
        sessions: (state: undefined[], action: any, fullState: any) => undefined[]
        sessionsLoading: (state: boolean, action: any, fullState: any) => boolean
        isLoadingNext: (state: boolean, action: any, fullState: any) => boolean
        offset: (state: null, action: any, fullState: any) => null
        selectedDate: (state: Moment, action: any, fullState: any) => Moment
    }
    selector: (
        state: any
    ) => {
        sessions: undefined[]
        sessionsLoading: boolean
        isLoadingNext: boolean
        offset: null
        selectedDate: Moment
    }
    selectors: {
        sessions: (state: any, props: any) => undefined[]
        sessionsLoading: (state: any, props: any) => boolean
        isLoadingNext: (state: any, props: any) => boolean
        offset: (state: any, props: any) => null
        selectedDate: (state: any, props: any) => Moment
        selectedDateURLparam: (state: any, props: any) => any
    }
    values: {
        sessions: undefined[]
        sessionsLoading: boolean
        isLoadingNext: boolean
        offset: null
        selectedDate: Moment
        selectedDateURLparam: any
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        selectedDateURLparam: (arg1: any) => any
    }
}
