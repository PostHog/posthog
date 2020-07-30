// Auto-generated with kea-typegen. DO NOT EDIT!

export interface trendsLogicType {
    key: any
    actionCreators: {
        loadResults: (
            refresh?: any
        ) => {
            type: 'load results (frontend.src.scenes.insights.trendsLogic)'
            payload: any
        }
        loadResultsSuccess: (
            results: never[]
        ) => {
            type: 'load results success (frontend.src.scenes.insights.trendsLogic)'
            payload: {
                results: never[]
            }
        }
        loadResultsFailure: (
            error: string
        ) => {
            type: 'load results failure (frontend.src.scenes.insights.trendsLogic)'
            payload: {
                error: string
            }
        }
        setFilters: (
            filters: any,
            mergeFilters?: any,
            fromUrl?: any
        ) => {
            type: 'set filters (frontend.src.scenes.insights.trendsLogic)'
            payload: { filters: any; mergeFilters: boolean; fromUrl: boolean }
        }
        setDisplay: (
            display: any
        ) => {
            type: 'set display (frontend.src.scenes.insights.trendsLogic)'
            payload: { display: any }
        }
        loadPeople: (
            action: any,
            label: any,
            day: any,
            breakdown_value: any
        ) => {
            type: 'load people (frontend.src.scenes.insights.trendsLogic)'
            payload: { action: any; label: any; day: any; breakdown_value: any }
        }
        loadMorePeople: () => {
            type: 'load more people (frontend.src.scenes.insights.trendsLogic)'
            payload: {
                value: boolean
            }
        }
        setLoadingMorePeople: (
            status: any
        ) => {
            type: 'set loading more people (frontend.src.scenes.insights.trendsLogic)'
            payload: { status: any }
        }
        setShowingPeople: (
            isShowing: any
        ) => {
            type: 'set showing people (frontend.src.scenes.insights.trendsLogic)'
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
            type: 'set people (frontend.src.scenes.insights.trendsLogic)'
            payload: { people: any; count: any; action: any; label: any; day: any; breakdown_value: any; next: any }
        }
    }
    actionKeys: {
        'load results (frontend.src.scenes.insights.trendsLogic)': 'loadResults'
        'load results success (frontend.src.scenes.insights.trendsLogic)': 'loadResultsSuccess'
        'load results failure (frontend.src.scenes.insights.trendsLogic)': 'loadResultsFailure'
        'set filters (frontend.src.scenes.insights.trendsLogic)': 'setFilters'
        'set display (frontend.src.scenes.insights.trendsLogic)': 'setDisplay'
        'load people (frontend.src.scenes.insights.trendsLogic)': 'loadPeople'
        'load more people (frontend.src.scenes.insights.trendsLogic)': 'loadMorePeople'
        'set loading more people (frontend.src.scenes.insights.trendsLogic)': 'setLoadingMorePeople'
        'set showing people (frontend.src.scenes.insights.trendsLogic)': 'setShowingPeople'
        'set people (frontend.src.scenes.insights.trendsLogic)': 'setPeople'
    }
    actionTypes: {
        loadResults: 'load results (frontend.src.scenes.insights.trendsLogic)'
        loadResultsSuccess: 'load results success (frontend.src.scenes.insights.trendsLogic)'
        loadResultsFailure: 'load results failure (frontend.src.scenes.insights.trendsLogic)'
        setFilters: 'set filters (frontend.src.scenes.insights.trendsLogic)'
        setDisplay: 'set display (frontend.src.scenes.insights.trendsLogic)'
        loadPeople: 'load people (frontend.src.scenes.insights.trendsLogic)'
        loadMorePeople: 'load more people (frontend.src.scenes.insights.trendsLogic)'
        setLoadingMorePeople: 'set loading more people (frontend.src.scenes.insights.trendsLogic)'
        setShowingPeople: 'set showing people (frontend.src.scenes.insights.trendsLogic)'
        setPeople: 'set people (frontend.src.scenes.insights.trendsLogic)'
    }
    actions: {
        loadResults: (refresh?: any) => void
        loadResultsSuccess: (results: never[]) => void
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
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'insights', 'trendsLogic']
    pathString: 'frontend.src.scenes.insights.trendsLogic'
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
        showingPeople: boolean
    }
    reducerOptions: any
    reducers: {
        results: (state: never[], action: any, fullState: any) => never[]
        resultsLoading: (state: boolean, action: any, fullState: any) => boolean
        filters: (state: any, action: any, fullState: any) => any
        people: (state: null, action: any, fullState: any) => null
        showingPeople: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        results: never[]
        resultsLoading: boolean
        filters: any
        people: null
        showingPeople: boolean
    }
    selectors: {
        results: (state: any, props: any) => never[]
        resultsLoading: (state: any, props: any) => boolean
        filters: (state: any, props: any) => any
        people: (state: any, props: any) => null
        showingPeople: (state: any, props: any) => boolean
        eventNames: (state: any, props: any) => string[]
        peopleAction: (state: any, props: any) => any
        peopleDay: (state: any, props: any) => any
    }
    values: {
        results: never[]
        resultsLoading: boolean
        filters: any
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
