// Auto-generated with kea-typegen. DO NOT EDIT!

export interface appUrlsLogicType {
    key: undefined
    actionCreators: {
        addUrl: (
            value: any
        ) => {
            type: 'add url (lib.components.AppEditorLink.appUrlsLogic)'
            payload: { value: any }
        }
        addUrlAndGo: (
            value: any
        ) => {
            type: 'add url and go (lib.components.AppEditorLink.appUrlsLogic)'
            payload: { value: any }
        }
        removeUrl: (
            index: any
        ) => {
            type: 'remove url (lib.components.AppEditorLink.appUrlsLogic)'
            payload: { index: any }
        }
        updateUrl: (
            index: any,
            value: any
        ) => {
            type: 'update url (lib.components.AppEditorLink.appUrlsLogic)'
            payload: { index: any; value: any }
        }
        loadSuggestions: () => {
            type: 'load suggestions (lib.components.AppEditorLink.appUrlsLogic)'
            payload: any
        }
        loadSuggestionsSuccess: (
            suggestions: never[]
        ) => {
            type: 'load suggestions success (lib.components.AppEditorLink.appUrlsLogic)'
            payload: {
                suggestions: never[]
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
        loadSuggestionsSuccess: (suggestions: never[]) => void
        loadSuggestionsFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: {
        suggestions: never[]
        suggestionsLoading: boolean
        appUrls: string[]
    }
    events: any
    path: ['lib', 'components', 'AppEditorLink', 'appUrlsLogic']
    pathString: 'lib.components.AppEditorLink.appUrlsLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        suggestions: never[]
        suggestionsLoading: boolean
        appUrls: string[]
    }
    reducerOptions: any
    reducers: {
        suggestions: (state: never[], action: any, fullState: any) => never[]
        suggestionsLoading: (state: boolean, action: any, fullState: any) => boolean
        appUrls: (state: string[], action: any, fullState: any) => string[]
    }
    selector: (
        state: any
    ) => {
        suggestions: never[]
        suggestionsLoading: boolean
        appUrls: string[]
    }
    selectors: {
        suggestions: (state: any, props: any) => never[]
        suggestionsLoading: (state: any, props: any) => boolean
        appUrls: (state: any, props: any) => string[]
    }
    values: {
        suggestions: never[]
        suggestionsLoading: boolean
        appUrls: string[]
    }
    _isKea: true
}
