// Auto-generated with kea-typegen. DO NOT EDIT!

export interface trendsLogicType {
    key: any
    actionCreators: {
        setActiveView: () => {
            type: 'set active view (scenes.trends.trendsLogic)'
            payload: any
        }
        setActiveViewSuccess: (
            results: never[]
        ) => {
            type: 'set active view success (scenes.trends.trendsLogic)'
            payload: {
                results: never[]
            }
        }
        setActiveViewFailure: (
            error: string
        ) => {
            type: 'set active view failure (scenes.trends.trendsLogic)'
            payload: {
                error: string
            }
        }
        loadResults: (
            refresh?: any
        ) => {
            type: 'load results (scenes.trends.trendsLogic)'
            payload: any
        }
        loadResultsSuccess: (
            results: never[]
        ) => {
            type: 'load results success (scenes.trends.trendsLogic)'
            payload: {
                results: never[]
            }
        }
        loadResultsFailure: (
            error: string
        ) => {
            type: 'load results failure (scenes.trends.trendsLogic)'
            payload: {
                error: string
            }
        }
        setFilters: (
            filters: any,
            mergeFilters?: any,
            fromUrl?: any
        ) => {
            type: 'set filters (scenes.trends.trendsLogic)'
            payload: { filters: any; mergeFilters: boolean; fromUrl: boolean }
        }
        setDisplay: (
            display: any
        ) => {
            type: 'set display (scenes.trends.trendsLogic)'
            payload: { display: any }
        }
        loadPeople: (
            action: any,
            label: any,
            day: any,
            breakdown_value: any
        ) => {
            type: 'load people (scenes.trends.trendsLogic)'
            payload: { action: any; label: any; day: any; breakdown_value: any }
        }
        loadMorePeople: () => {
            type: 'load more people (scenes.trends.trendsLogic)'
            payload: {
                value: boolean
            }
        }
        setLoadingMorePeople: (
            status: any
        ) => {
            type: 'set loading more people (scenes.trends.trendsLogic)'
            payload: { status: any }
        }
        setShowingPeople: (
            isShowing: any
        ) => {
            type: 'set showing people (scenes.trends.trendsLogic)'
            payload: { isShowing: any }
        }
        setPeople: (
            people: any,
            count: any,
            action: any,
            label: any,
            day: any,
            breakdown_value: any,
            next: any
        ) => {
            type: 'set people (scenes.trends.trendsLogic)'
            payload: { people: any; count: any; action: any; label: any; day: any; breakdown_value: any; next: any }
        }
        setActiveView: (
            type: any
        ) => {
            type: 'set active view (scenes.trends.trendsLogic)'
            payload: { type: any }
        }
        setCachedUrl: (
            type: any,
            url: any
        ) => {
            type: 'set cached url (scenes.trends.trendsLogic)'
            payload: { type: any; url: any }
        }
    }
    actionKeys: {
        'set active view (scenes.trends.trendsLogic)': 'setActiveView'
        'set active view success (scenes.trends.trendsLogic)': 'setActiveViewSuccess'
        'set active view failure (scenes.trends.trendsLogic)': 'setActiveViewFailure'
        'load results (scenes.trends.trendsLogic)': 'loadResults'
        'load results success (scenes.trends.trendsLogic)': 'loadResultsSuccess'
        'load results failure (scenes.trends.trendsLogic)': 'loadResultsFailure'
        'set filters (scenes.trends.trendsLogic)': 'setFilters'
        'set display (scenes.trends.trendsLogic)': 'setDisplay'
        'load people (scenes.trends.trendsLogic)': 'loadPeople'
        'load more people (scenes.trends.trendsLogic)': 'loadMorePeople'
        'set loading more people (scenes.trends.trendsLogic)': 'setLoadingMorePeople'
        'set showing people (scenes.trends.trendsLogic)': 'setShowingPeople'
        'set people (scenes.trends.trendsLogic)': 'setPeople'
        'set active view (scenes.trends.trendsLogic)': 'setActiveView'
        'set cached url (scenes.trends.trendsLogic)': 'setCachedUrl'
    }
    actionTypes: {
        setActiveView: 'set active view (scenes.trends.trendsLogic)'
        setActiveViewSuccess: 'set active view success (scenes.trends.trendsLogic)'
        setActiveViewFailure: 'set active view failure (scenes.trends.trendsLogic)'
        loadResults: 'load results (scenes.trends.trendsLogic)'
        loadResultsSuccess: 'load results success (scenes.trends.trendsLogic)'
        loadResultsFailure: 'load results failure (scenes.trends.trendsLogic)'
        setFilters: 'set filters (scenes.trends.trendsLogic)'
        setDisplay: 'set display (scenes.trends.trendsLogic)'
        loadPeople: 'load people (scenes.trends.trendsLogic)'
        loadMorePeople: 'load more people (scenes.trends.trendsLogic)'
        setLoadingMorePeople: 'set loading more people (scenes.trends.trendsLogic)'
        setShowingPeople: 'set showing people (scenes.trends.trendsLogic)'
        setPeople: 'set people (scenes.trends.trendsLogic)'
        setActiveView: 'set active view (scenes.trends.trendsLogic)'
        setCachedUrl: 'set cached url (scenes.trends.trendsLogic)'
    }
    actions: {
        setActiveView: () => {
            type: 'set active view (scenes.trends.trendsLogic)'
            payload: any
        }
        setActiveViewSuccess: (
            results: never[]
        ) => {
            type: 'set active view success (scenes.trends.trendsLogic)'
            payload: {
                results: never[]
            }
        }
        setActiveViewFailure: (
            error: string
        ) => {
            type: 'set active view failure (scenes.trends.trendsLogic)'
            payload: {
                error: string
            }
        }
        loadResults: (
            refresh?: any
        ) => {
            type: 'load results (scenes.trends.trendsLogic)'
            payload: any
        }
        loadResultsSuccess: (
            results: never[]
        ) => {
            type: 'load results success (scenes.trends.trendsLogic)'
            payload: {
                results: never[]
            }
        }
        loadResultsFailure: (
            error: string
        ) => {
            type: 'load results failure (scenes.trends.trendsLogic)'
            payload: {
                error: string
            }
        }
        setFilters: (
            filters: any,
            mergeFilters?: any,
            fromUrl?: any
        ) => {
            type: 'set filters (scenes.trends.trendsLogic)'
            payload: { filters: any; mergeFilters: boolean; fromUrl: boolean }
        }
        setDisplay: (
            display: any
        ) => {
            type: 'set display (scenes.trends.trendsLogic)'
            payload: { display: any }
        }
        loadPeople: (
            action: any,
            label: any,
            day: any,
            breakdown_value: any
        ) => {
            type: 'load people (scenes.trends.trendsLogic)'
            payload: { action: any; label: any; day: any; breakdown_value: any }
        }
        loadMorePeople: () => {
            type: 'load more people (scenes.trends.trendsLogic)'
            payload: {
                value: boolean
            }
        }
        setLoadingMorePeople: (
            status: any
        ) => {
            type: 'set loading more people (scenes.trends.trendsLogic)'
            payload: { status: any }
        }
        setShowingPeople: (
            isShowing: any
        ) => {
            type: 'set showing people (scenes.trends.trendsLogic)'
            payload: { isShowing: any }
        }
        setPeople: (
            people: any,
            count: any,
            action: any,
            label: any,
            day: any,
            breakdown_value: any,
            next: any
        ) => {
            type: 'set people (scenes.trends.trendsLogic)'
            payload: { people: any; count: any; action: any; label: any; day: any; breakdown_value: any; next: any }
        }
        setActiveView: (
            type: any
        ) => {
            type: 'set active view (scenes.trends.trendsLogic)'
            payload: { type: any }
        }
        setCachedUrl: (
            type: any,
            url: any
        ) => {
            type: 'set cached url (scenes.trends.trendsLogic)'
            payload: { type: any; url: any }
        }
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['scenes', 'trends', 'trendsLogic']
    pathString: 'scenes.trends.trendsLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        results: never[]
        resultsLoading: boolean
        filters: any
        people: null
        cachedUrls: {}
        showingPeople: boolean
    }
    reducerOptions: any
    reducers: {
        results: (state: never[], action: any, fullState: any) => never[]
        resultsLoading: (state: boolean, action: any, fullState: any) => boolean
        filters: (state: any, action: any, fullState: any) => any
        people: (state: null, action: any, fullState: any) => null
        cachedUrls: (state: {}, action: any, fullState: any) => {}
        showingPeople: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        results: never[]
        resultsLoading: boolean
        filters: any
        people: null
        cachedUrls: {}
        showingPeople: boolean
    }
    selectors: {
        results: (state: any, props: any) => never[]
        resultsLoading: (state: any, props: any) => boolean
        filters: (state: any, props: any) => any
        people: (state: any, props: any) => null
        cachedUrls: (state: any, props: any) => {}
        showingPeople: (state: any, props: any) => boolean
        eventNames: (state: any, props: any) => string[]
        activeView: (state: any, props: any) => string
        peopleAction: (state: any, props: any) => any
        peopleDay: (state: any, props: any) => any
    }
    values: {
        results: never[]
        resultsLoading: boolean
        filters: any
        people: null
        cachedUrls: {}
        showingPeople: boolean
        eventNames: string[]
        activeView: string
        peopleAction: any
        peopleDay: any
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        activeView: (arg1: any) => string
        peopleAction: (arg1: any, arg2: any) => any
        peopleDay: (arg1: any) => any
    }
}
