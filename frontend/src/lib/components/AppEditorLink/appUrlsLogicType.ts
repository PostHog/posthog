// Auto-generated with kea-typegen. DO NOT EDIT!

export interface appUrlsLogicType {
    key: any
    actionCreators: {
        addUrl: (
            value: any
        ) => {
            type: 'add url (frontend.src.lib.components.AppEditorLink.appUrlsLogic)'
            payload: { value: any }
        }
        addUrlAndGo: (
            value: any
        ) => {
            type: 'add url and go (frontend.src.lib.components.AppEditorLink.appUrlsLogic)'
            payload: { value: any }
        }
        removeUrl: (
            index: any
        ) => {
            type: 'remove url (frontend.src.lib.components.AppEditorLink.appUrlsLogic)'
            payload: { index: any }
        }
        updateUrl: (
            index: any,
            value: any
        ) => {
            type: 'update url (frontend.src.lib.components.AppEditorLink.appUrlsLogic)'
            payload: { index: any; value: any }
        }
        loadSuggestions: () => {
            type: 'load suggestions (frontend.src.lib.components.AppEditorLink.appUrlsLogic)'
            payload: any
        }
        loadSuggestionsSuccess: (
            suggestions: never[]
        ) => {
            type: 'load suggestions success (frontend.src.lib.components.AppEditorLink.appUrlsLogic)'
            payload: {
                suggestions: never[]
            }
        }
        loadSuggestionsFailure: (
            error: string
        ) => {
            type: 'load suggestions failure (frontend.src.lib.components.AppEditorLink.appUrlsLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'add url (frontend.src.lib.components.AppEditorLink.appUrlsLogic)': 'addUrl'
        'add url and go (frontend.src.lib.components.AppEditorLink.appUrlsLogic)': 'addUrlAndGo'
        'remove url (frontend.src.lib.components.AppEditorLink.appUrlsLogic)': 'removeUrl'
        'update url (frontend.src.lib.components.AppEditorLink.appUrlsLogic)': 'updateUrl'
        'load suggestions (frontend.src.lib.components.AppEditorLink.appUrlsLogic)': 'loadSuggestions'
        'load suggestions success (frontend.src.lib.components.AppEditorLink.appUrlsLogic)': 'loadSuggestionsSuccess'
        'load suggestions failure (frontend.src.lib.components.AppEditorLink.appUrlsLogic)': 'loadSuggestionsFailure'
    }
    actionTypes: {
        addUrl: 'add url (frontend.src.lib.components.AppEditorLink.appUrlsLogic)'
        addUrlAndGo: 'add url and go (frontend.src.lib.components.AppEditorLink.appUrlsLogic)'
        removeUrl: 'remove url (frontend.src.lib.components.AppEditorLink.appUrlsLogic)'
        updateUrl: 'update url (frontend.src.lib.components.AppEditorLink.appUrlsLogic)'
        loadSuggestions: 'load suggestions (frontend.src.lib.components.AppEditorLink.appUrlsLogic)'
        loadSuggestionsSuccess: 'load suggestions success (frontend.src.lib.components.AppEditorLink.appUrlsLogic)'
        loadSuggestionsFailure: 'load suggestions failure (frontend.src.lib.components.AppEditorLink.appUrlsLogic)'
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
    defaults: any
    events: any
    path: ['frontend', 'src', 'lib', 'components', 'AppEditorLink', 'appUrlsLogic']
    pathString: 'frontend.src.lib.components.AppEditorLink.appUrlsLogic'
    propTypes: any
    props: Record<string, any>
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
