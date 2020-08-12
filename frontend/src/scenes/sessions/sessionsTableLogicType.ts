// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic, BreakPointFunction } from 'kea'

export interface sessionsTableLogicType extends Logic {
    actionCreators: {
        loadSessions: (
            selectedDate: any
        ) => {
            type: 'load sessions (scenes.sessions.sessionsTableLogic)'
            payload: any
        }
        loadSessionsSuccess: (
            sessions: any[]
        ) => {
            type: 'load sessions success (scenes.sessions.sessionsTableLogic)'
            payload: {
                sessions: any[]
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
            payload: {
                offset: any
            }
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
            payload: {
                sessions: any
            }
        }
        dateChanged: (
            date: any
        ) => {
            type: 'date changed (scenes.sessions.sessionsTableLogic)'
            payload: {
                date: any
            }
        }
        setDate: (
            date: any
        ) => {
            type: 'set date (scenes.sessions.sessionsTableLogic)'
            payload: {
                date: any
            }
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
        loadSessions: (selectedDate: any) => void
        loadSessionsSuccess: (sessions: any[]) => void
        loadSessionsFailure: (error: string) => void
        setOffset: (offset: any) => void
        fetchNextSessions: () => void
        appendNewSessions: (sessions: any) => void
        dateChanged: (date: any) => void
        setDate: (date: any) => void
    }
    constants: {}
    defaults: {
        sessions: any[]
        sessionsLoading: boolean
        isLoadingNext: boolean
        offset: null
        selectedDate: Moment
    }
    events: {
        afterMount: () => void
    }
    key: undefined
    listeners: {
        fetchNextSessions: ((
            payload: {
                value: boolean
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'fetch next sessions (scenes.sessions.sessionsTableLogic)'
                payload: {
                    value: boolean
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        dateChanged: ((
            payload: {
                date: any
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'date changed (scenes.sessions.sessionsTableLogic)'
                payload: {
                    date: any
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
    }
    path: ['scenes', 'sessions', 'sessionsTableLogic']
    pathString: 'scenes.sessions.sessionsTableLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        sessions: any[]
        sessionsLoading: boolean
        isLoadingNext: boolean
        offset: null
        selectedDate: Moment
    }
    reducerOptions: {}
    reducers: {
        sessions: (state: any[], action: any, fullState: any) => any[]
        sessionsLoading: (state: boolean, action: any, fullState: any) => boolean
        isLoadingNext: (state: boolean, action: any, fullState: any) => boolean
        offset: (state: null, action: any, fullState: any) => null
        selectedDate: (state: Moment, action: any, fullState: any) => Moment
    }
    selector: (
        state: any
    ) => {
        sessions: any[]
        sessionsLoading: boolean
        isLoadingNext: boolean
        offset: null
        selectedDate: Moment
    }
    selectors: {
        sessions: (state: any, props: any) => any[]
        sessionsLoading: (state: any, props: any) => boolean
        isLoadingNext: (state: any, props: any) => boolean
        offset: (state: any, props: any) => null
        selectedDate: (state: any, props: any) => Moment
        selectedDateURLparam: (state: any, props: any) => any
    }
    sharedListeners: {}
    values: {
        sessions: any[]
        sessionsLoading: boolean
        isLoadingNext: boolean
        offset: null
        selectedDate: Moment
        selectedDateURLparam: any
    }
    _isKea: true
    _isKeaWithKey: false
    __keaTypeGenInternalSelectorTypes: {
        selectedDateURLparam: (arg1: any) => any
    }
}
