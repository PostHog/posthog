// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic, BreakPointFunction } from 'kea'

export interface appUrlsLogicType extends Logic {
    actionCreators: {
        addUrl: (
            value: any
        ) => {
            type: 'add url (lib.components.AppEditorLink.appUrlsLogic)'
            payload: {
                value: any
            }
        }
        addUrlAndGo: (
            value: any
        ) => {
            type: 'add url and go (lib.components.AppEditorLink.appUrlsLogic)'
            payload: {
                value: any
            }
        }
        removeUrl: (
            index: any
        ) => {
            type: 'remove url (lib.components.AppEditorLink.appUrlsLogic)'
            payload: {
                index: any
            }
        }
        updateUrl: (
            index: any,
            value: any
        ) => {
            type: 'update url (lib.components.AppEditorLink.appUrlsLogic)'
            payload: {
                index: any
                value: any
            }
        }
        loadSuggestions: () => {
            type: 'load suggestions (lib.components.AppEditorLink.appUrlsLogic)'
            payload: any
        }
        loadSuggestionsSuccess: (
            suggestions: any[]
        ) => {
            type: 'load suggestions success (lib.components.AppEditorLink.appUrlsLogic)'
            payload: {
                suggestions: any[]
            }
        }
        loadSuggestionsFailure: (
            error: string
        ) => {
            type: 'load suggestions failure (lib.components.AppEditorLink.appUrlsLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'add url (lib.components.AppEditorLink.appUrlsLogic)': 'addUrl'
        'add url and go (lib.components.AppEditorLink.appUrlsLogic)': 'addUrlAndGo'
        'remove url (lib.components.AppEditorLink.appUrlsLogic)': 'removeUrl'
        'update url (lib.components.AppEditorLink.appUrlsLogic)': 'updateUrl'
        'load suggestions (lib.components.AppEditorLink.appUrlsLogic)': 'loadSuggestions'
        'load suggestions success (lib.components.AppEditorLink.appUrlsLogic)': 'loadSuggestionsSuccess'
        'load suggestions failure (lib.components.AppEditorLink.appUrlsLogic)': 'loadSuggestionsFailure'
    }
    actionTypes: {
        addUrl: 'add url (lib.components.AppEditorLink.appUrlsLogic)'
        addUrlAndGo: 'add url and go (lib.components.AppEditorLink.appUrlsLogic)'
        removeUrl: 'remove url (lib.components.AppEditorLink.appUrlsLogic)'
        updateUrl: 'update url (lib.components.AppEditorLink.appUrlsLogic)'
        loadSuggestions: 'load suggestions (lib.components.AppEditorLink.appUrlsLogic)'
        loadSuggestionsSuccess: 'load suggestions success (lib.components.AppEditorLink.appUrlsLogic)'
        loadSuggestionsFailure: 'load suggestions failure (lib.components.AppEditorLink.appUrlsLogic)'
    }
    actions: {
        addUrl: (value: any) => void
        addUrlAndGo: (value: any) => void
        removeUrl: (index: any) => void
        updateUrl: (index: any, value: any) => void
        loadSuggestions: () => void
        loadSuggestionsSuccess: (suggestions: any[]) => void
        loadSuggestionsFailure: (error: string) => void
    }
    constants: {}
    defaults: {
        suggestions: any[]
        suggestionsLoading: boolean
        appUrls: (state: any) => string[]
    }
    events: {
        afterMount: () => void
    }
    key: undefined
    listeners: {
        addUrlAndGo: ((
            payload: {
                value: any
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'add url and go (lib.components.AppEditorLink.appUrlsLogic)'
                payload: {
                    value: any
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        removeUrl: ((
            payload: {
                index: any
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'remove url (lib.components.AppEditorLink.appUrlsLogic)'
                payload: {
                    index: any
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
        updateUrl: ((
            payload: {
                index: any
                value: any
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'update url (lib.components.AppEditorLink.appUrlsLogic)'
                payload: {
                    index: any
                    value: any
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
    }
    path: ['lib', 'components', 'AppEditorLink', 'appUrlsLogic']
    pathString: 'lib.components.AppEditorLink.appUrlsLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        suggestions: any[]
        suggestionsLoading: boolean
        appUrls: (state: any) => string[]
    }
    reducerOptions: {}
    reducers: {
        suggestions: (state: any[], action: any, fullState: any) => any[]
        suggestionsLoading: (state: boolean, action: any, fullState: any) => boolean
        appUrls: (state: (state: any) => string[], action: any, fullState: any) => (state: any) => string[]
    }
    selector: (
        state: any
    ) => {
        suggestions: any[]
        suggestionsLoading: boolean
        appUrls: (state: any) => string[]
    }
    selectors: {
        suggestions: (state: any, props: any) => any[]
        suggestionsLoading: (state: any, props: any) => boolean
        appUrls: (state: any, props: any) => (state: any) => string[]
    }
    sharedListeners: {
        saveAppUrls: (
            payload: any,
            breakpoint: BreakPointFunction,
            action: {
                type: string
                payload: any
            },
            previousState: any
        ) => void | Promise<void>
    }
    values: {
        suggestions: any[]
        suggestionsLoading: boolean
        appUrls: (state: any) => string[]
    }
    _isKea: true
    _isKeaWithKey: false
}
