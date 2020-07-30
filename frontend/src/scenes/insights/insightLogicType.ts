// Auto-generated with kea-typegen. DO NOT EDIT!

export interface insightLogicType {
    key: any
    actionCreators: {
        setActiveView: (
            type: any
        ) => {
            type: 'set active view (frontend.src.scenes.insights.insightLogic)'
            payload: { type: any }
        }
        updateActiveView: (
            type: any
        ) => {
            type: 'update active view (frontend.src.scenes.insights.insightLogic)'
            payload: { type: any }
        }
        setCachedUrl: (
            type: any,
            url: any
        ) => {
            type: 'set cached url (frontend.src.scenes.insights.insightLogic)'
            payload: { type: any; url: any }
        }
        setAllFilters: (
            filters: any
        ) => {
            type: 'set all filters (frontend.src.scenes.insights.insightLogic)'
            payload: { filters: any }
        }
    }
    actionKeys: {
        'set active view (frontend.src.scenes.insights.insightLogic)': 'setActiveView'
        'update active view (frontend.src.scenes.insights.insightLogic)': 'updateActiveView'
        'set cached url (frontend.src.scenes.insights.insightLogic)': 'setCachedUrl'
        'set all filters (frontend.src.scenes.insights.insightLogic)': 'setAllFilters'
    }
    actionTypes: {
        setActiveView: 'set active view (frontend.src.scenes.insights.insightLogic)'
        updateActiveView: 'update active view (frontend.src.scenes.insights.insightLogic)'
        setCachedUrl: 'set cached url (frontend.src.scenes.insights.insightLogic)'
        setAllFilters: 'set all filters (frontend.src.scenes.insights.insightLogic)'
    }
    actions: {
        setActiveView: (type: any) => void
        updateActiveView: (type: any) => void
        setCachedUrl: (type: any, url: any) => void
        setAllFilters: (filters: any) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'insights', 'insightLogic']
    pathString: 'frontend.src.scenes.insights.insightLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        cachedUrls: {}
        activeView: string
        allFilters: {}
    }
    reducerOptions: any
    reducers: {
        cachedUrls: (state: {}, action: any, fullState: any) => {}
        activeView: (state: string, action: any, fullState: any) => string
        allFilters: (state: {}, action: any, fullState: any) => {}
    }
    selector: (
        state: any
    ) => {
        cachedUrls: {}
        activeView: string
        allFilters: {}
    }
    selectors: {
        cachedUrls: (state: any, props: any) => {}
        activeView: (state: any, props: any) => string
        allFilters: (state: any, props: any) => {}
    }
    values: {
        cachedUrls: {}
        activeView: string
        allFilters: {}
    }
    _isKea: true
}
