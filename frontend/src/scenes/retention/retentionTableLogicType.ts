// Auto-generated with kea-typegen. DO NOT EDIT!

export interface retentionTableLogicType {
    key: any
    actionCreators: {
        loadRetention: () => {
            type: 'load retention (frontend.src.scenes.retention.retentionTableLogic)'
            payload: any
        }
        loadRetentionSuccess: (retention: {}) => {
            type: 'load retention success (frontend.src.scenes.retention.retentionTableLogic)'
            payload: {
                retention: {}
            }
        }
        loadRetentionFailure: (
            error: string
        ) => {
            type: 'load retention failure (frontend.src.scenes.retention.retentionTableLogic)'
            payload: {
                error: string
            }
        }
        loadPeople: (
            rowIndex: any
        ) => {
            type: 'load people (frontend.src.scenes.retention.retentionTableLogic)'
            payload: any
        }
        loadPeopleSuccess: (people: {}) => {
            type: 'load people success (frontend.src.scenes.retention.retentionTableLogic)'
            payload: {
                people: {}
            }
        }
        loadPeopleFailure: (
            error: string
        ) => {
            type: 'load people failure (frontend.src.scenes.retention.retentionTableLogic)'
            payload: {
                error: string
            }
        }
        createInsight: (
            filters: Record<string, any>
        ) => {
            type: 'create insight (frontend.src.scenes.retention.retentionTableLogic)'
            payload: {
                filters: Record<string, any>
            }
        }
        setProperties: (
            properties: any
        ) => {
            type: 'set properties (frontend.src.scenes.retention.retentionTableLogic)'
            payload: { properties: any }
        }
        setFilters: (
            filters: any
        ) => {
            type: 'set filters (frontend.src.scenes.retention.retentionTableLogic)'
            payload: { filters: any }
        }
        loadMore: (
            selectedIndex: any
        ) => {
            type: 'load more (frontend.src.scenes.retention.retentionTableLogic)'
            payload: { selectedIndex: any }
        }
        loadMorePeople: (
            selectedIndex: any,
            peopleIds: any
        ) => {
            type: 'load more people (frontend.src.scenes.retention.retentionTableLogic)'
            payload: { selectedIndex: any; peopleIds: any }
        }
        updatePeople: (
            selectedIndex: any,
            people: any
        ) => {
            type: 'update people (frontend.src.scenes.retention.retentionTableLogic)'
            payload: { selectedIndex: any; people: any }
        }
        updateRetention: (
            retention: any
        ) => {
            type: 'update retention (frontend.src.scenes.retention.retentionTableLogic)'
            payload: { retention: any }
        }
    }
    actionKeys: {
        'load retention (frontend.src.scenes.retention.retentionTableLogic)': 'loadRetention'
        'load retention success (frontend.src.scenes.retention.retentionTableLogic)': 'loadRetentionSuccess'
        'load retention failure (frontend.src.scenes.retention.retentionTableLogic)': 'loadRetentionFailure'
        'load people (frontend.src.scenes.retention.retentionTableLogic)': 'loadPeople'
        'load people success (frontend.src.scenes.retention.retentionTableLogic)': 'loadPeopleSuccess'
        'load people failure (frontend.src.scenes.retention.retentionTableLogic)': 'loadPeopleFailure'
        'create insight (frontend.src.scenes.retention.retentionTableLogic)': 'createInsight'
        'set properties (frontend.src.scenes.retention.retentionTableLogic)': 'setProperties'
        'set filters (frontend.src.scenes.retention.retentionTableLogic)': 'setFilters'
        'load more (frontend.src.scenes.retention.retentionTableLogic)': 'loadMore'
        'load more people (frontend.src.scenes.retention.retentionTableLogic)': 'loadMorePeople'
        'update people (frontend.src.scenes.retention.retentionTableLogic)': 'updatePeople'
        'update retention (frontend.src.scenes.retention.retentionTableLogic)': 'updateRetention'
    }
    actionTypes: {
        loadRetention: 'load retention (frontend.src.scenes.retention.retentionTableLogic)'
        loadRetentionSuccess: 'load retention success (frontend.src.scenes.retention.retentionTableLogic)'
        loadRetentionFailure: 'load retention failure (frontend.src.scenes.retention.retentionTableLogic)'
        loadPeople: 'load people (frontend.src.scenes.retention.retentionTableLogic)'
        loadPeopleSuccess: 'load people success (frontend.src.scenes.retention.retentionTableLogic)'
        loadPeopleFailure: 'load people failure (frontend.src.scenes.retention.retentionTableLogic)'
        createInsight: 'create insight (frontend.src.scenes.retention.retentionTableLogic)'
        setProperties: 'set properties (frontend.src.scenes.retention.retentionTableLogic)'
        setFilters: 'set filters (frontend.src.scenes.retention.retentionTableLogic)'
        loadMore: 'load more (frontend.src.scenes.retention.retentionTableLogic)'
        loadMorePeople: 'load more people (frontend.src.scenes.retention.retentionTableLogic)'
        updatePeople: 'update people (frontend.src.scenes.retention.retentionTableLogic)'
        updateRetention: 'update retention (frontend.src.scenes.retention.retentionTableLogic)'
    }
    actions: {
        loadRetention: () => void
        loadRetentionSuccess: (retention: {}) => void
        loadRetentionFailure: (error: string) => void
        loadPeople: (rowIndex: any) => void
        loadPeopleSuccess: (people: {}) => void
        loadPeopleFailure: (error: string) => void
        createInsight: (filters: Record<string, any>) => void
        setProperties: (properties: any) => void
        setFilters: (filters: any) => void
        loadMore: (selectedIndex: any) => void
        loadMorePeople: (selectedIndex: any, peopleIds: any) => void
        updatePeople: (selectedIndex: any, people: any) => void
        updateRetention: (retention: any) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'retention', 'retentionTableLogic']
    pathString: 'frontend.src.scenes.retention.retentionTableLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        retention: {}
        retentionLoading: boolean
        people: {}
        peopleLoading: boolean
        initialPathname: (state: any) => any
        properties: never[]
        filters: {}
        loadingMore: boolean
    }
    reducerOptions: any
    reducers: {
        retention: (state: {}, action: any, fullState: any) => {}
        retentionLoading: (state: boolean, action: any, fullState: any) => boolean
        people: (state: {}, action: any, fullState: any) => {}
        peopleLoading: (state: boolean, action: any, fullState: any) => boolean
        initialPathname: (state: (state: any) => any, action: any, fullState: any) => (state: any) => any
        properties: (state: never[], action: any, fullState: any) => never[]
        filters: (state: {}, action: any, fullState: any) => {}
        loadingMore: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        retention: {}
        retentionLoading: boolean
        people: {}
        peopleLoading: boolean
        initialPathname: (state: any) => any
        properties: never[]
        filters: {}
        loadingMore: boolean
    }
    selectors: {
        retention: (state: any, props: any) => {}
        retentionLoading: (state: any, props: any) => boolean
        people: (state: any, props: any) => {}
        peopleLoading: (state: any, props: any) => boolean
        initialPathname: (state: any, props: any) => (state: any) => any
        properties: (state: any, props: any) => never[]
        filters: (state: any, props: any) => {}
        loadingMore: (state: any, props: any) => boolean
        propertiesForUrl: (state: any, props: any) => '' | { properties: any }
        startEntity: (state: any, props: any) => any
    }
    values: {
        retention: {}
        retentionLoading: boolean
        people: {}
        peopleLoading: boolean
        initialPathname: (state: any) => any
        properties: never[]
        filters: {}
        loadingMore: boolean
        propertiesForUrl: '' | { properties: any }
        startEntity: any
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        propertiesForUrl: (arg1: any) => '' | { properties: any }
        startEntity: (arg1: any) => any
    }
}
