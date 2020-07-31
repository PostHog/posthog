// Auto-generated with kea-typegen. DO NOT EDIT!

export interface trendsLogicType {
    key: unknown
    actionCreators: {
        loadResults: (
            refresh?: any
        ) => {
            type: 'load results (scenes.insights.trendsLogic)'
            payload: any
        }
        loadResultsSuccess: (
            results: any[]
        ) => {
            type: 'load results success (scenes.insights.trendsLogic)'
            payload: {
                results: any[]
            }
        }
        loadResultsFailure: (
            error: string
        ) => {
            type: 'load results failure (scenes.insights.trendsLogic)'
            payload: {
                error: string
            }
        }
        setFilters: (
            filters: any,
            mergeFilters?: any,
            fromUrl?: any
        ) => {
            type: 'set filters (scenes.insights.trendsLogic)'
            payload: { filters: any; mergeFilters: boolean; fromUrl: boolean }
        }
        setDisplay: (
            display: any
        ) => {
            type: 'set display (scenes.insights.trendsLogic)'
            payload: { display: any }
        }
        loadPeople: (
            action: any,
            label: any,
            day: any,
            breakdown_value: any
        ) => {
            type: 'load people (scenes.insights.trendsLogic)'
            payload: { action: any; label: any; day: any; breakdown_value: any }
        }
        loadMorePeople: () => {
            type: 'load more people (scenes.insights.trendsLogic)'
            payload: {
                value: boolean
            }
        }
        setLoadingMorePeople: (
            status: any
        ) => {
            type: 'set loading more people (scenes.insights.trendsLogic)'
            payload: { status: any }
        }
        setShowingPeople: (
            isShowing: any
        ) => {
            type: 'set showing people (scenes.insights.trendsLogic)'
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
            type: 'set people (scenes.insights.trendsLogic)'
            payload: { people: any; count: any; action: any; label: any; day: any; breakdown_value: any; next: any }
        }
    }
    actionKeys: {
        'load results (scenes.insights.trendsLogic)': 'loadResults'
        'load results success (scenes.insights.trendsLogic)': 'loadResultsSuccess'
        'load results failure (scenes.insights.trendsLogic)': 'loadResultsFailure'
        'set filters (scenes.insights.trendsLogic)': 'setFilters'
        'set display (scenes.insights.trendsLogic)': 'setDisplay'
        'load people (scenes.insights.trendsLogic)': 'loadPeople'
        'load more people (scenes.insights.trendsLogic)': 'loadMorePeople'
        'set loading more people (scenes.insights.trendsLogic)': 'setLoadingMorePeople'
        'set showing people (scenes.insights.trendsLogic)': 'setShowingPeople'
        'set people (scenes.insights.trendsLogic)': 'setPeople'
    }
    actionTypes: {
        loadResults: 'load results (scenes.insights.trendsLogic)'
        loadResultsSuccess: 'load results success (scenes.insights.trendsLogic)'
        loadResultsFailure: 'load results failure (scenes.insights.trendsLogic)'
        setFilters: 'set filters (scenes.insights.trendsLogic)'
        setDisplay: 'set display (scenes.insights.trendsLogic)'
        loadPeople: 'load people (scenes.insights.trendsLogic)'
        loadMorePeople: 'load more people (scenes.insights.trendsLogic)'
        setLoadingMorePeople: 'set loading more people (scenes.insights.trendsLogic)'
        setShowingPeople: 'set showing people (scenes.insights.trendsLogic)'
        setPeople: 'set people (scenes.insights.trendsLogic)'
    }
    actions: {
        loadResults: (refresh?: any) => void
        loadResultsSuccess: (results: any[]) => void
        loadResultsFailure: (error: string) => void
        setFilters: (filters: any, mergeFilters?: any, fromUrl?: any) => void
        setDisplay: (display: any) => void
        loadPeople: (action: any, label: any, day: any, breakdown_value: any) => void
        loadMorePeople: () => void
        setLoadingMorePeople: (status: any) => void
        setShowingPeople: (isShowing: any) => void
        setPeople: (people: any, count: any, action: any, label: any, day: any, breakdown_value: any, next: any) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: {
        results: any[]
        resultsLoading: boolean
        filters: unknown
        people: null
        showingPeople: boolean
    }
    events: any
    path: ['scenes', 'insights', 'trendsLogic']
    pathString: 'scenes.insights.trendsLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        results: any[]
        resultsLoading: boolean
        filters: unknown
        people: null
        showingPeople: boolean
    }
    reducerOptions: any
    reducers: {
        results: (state: any[], action: any, fullState: any) => any[]
        resultsLoading: (state: boolean, action: any, fullState: any) => boolean
        filters: (state: unknown, action: any, fullState: any) => unknown
        people: (state: null, action: any, fullState: any) => null
        showingPeople: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        results: any[]
        resultsLoading: boolean
        filters: unknown
        people: null
        showingPeople: boolean
    }
    selectors: {
        results: (state: any, props: any) => any[]
        resultsLoading: (state: any, props: any) => boolean
        filters: (state: any, props: any) => unknown
        people: (state: any, props: any) => null
        showingPeople: (state: any, props: any) => boolean
        eventNames: (state: any, props: any) => string[]
        peopleAction: (state: any, props: any) => any
        peopleDay: (state: any, props: any) => any
    }
    values: {
        results: any[]
        resultsLoading: boolean
        filters: unknown
        people: null
        showingPeople: boolean
        eventNames: string[]
        peopleAction: any
        peopleDay: any
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        peopleAction: (arg1: any, arg2: any) => any
        peopleDay: (arg1: any) => any
    }
}
