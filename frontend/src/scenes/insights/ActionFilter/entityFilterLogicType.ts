// Auto-generated with kea-typegen. DO NOT EDIT!

export interface entityFilterLogicType {
    key: any
    actionCreators: {
        selectFilter: (
            filter: any
        ) => {
            type: 'select filter (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
            payload: { filter: any }
        }
        updateFilterMath: (
            filter: any
        ) => {
            type: 'update filter math (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
            payload: { type: any; value: any; math: any; math_property: any; index: any }
        }
        updateFilter: (
            filter: any
        ) => {
            type: 'update filter (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
            payload: { type: any; index: any; value: any; name: any }
        }
        removeLocalFilter: (
            filter: any
        ) => {
            type: 'remove local filter (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
            payload: { value: any; type: any; index: any }
        }
        addFilter: () => {
            type: 'add filter (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
            payload: {
                value: boolean
            }
        }
        updateFilterProperty: (
            filter: any
        ) => {
            type: 'update filter property (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
            payload: { properties: any; index: any }
        }
        setFilters: (
            filters: any
        ) => {
            type: 'set filters (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
            payload: { filters: any }
        }
        setLocalFilters: (
            filters: any
        ) => {
            type: 'set local filters (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
            payload: { filters: any }
        }
    }
    actionKeys: {
        'select filter (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)': 'selectFilter'
        'update filter math (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)': 'updateFilterMath'
        'update filter (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)': 'updateFilter'
        'remove local filter (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)': 'removeLocalFilter'
        'add filter (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)': 'addFilter'
        'update filter property (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)': 'updateFilterProperty'
        'set filters (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)': 'setFilters'
        'set local filters (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)': 'setLocalFilters'
    }
    actionTypes: {
        selectFilter: 'select filter (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
        updateFilterMath: 'update filter math (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
        updateFilter: 'update filter (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
        removeLocalFilter: 'remove local filter (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
        addFilter: 'add filter (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
        updateFilterProperty: 'update filter property (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
        setFilters: 'set filters (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
        setLocalFilters: 'set local filters (frontend.src.scenes.insights.ActionFilter.entityFilterLogic)'
    }
    actions: {
        selectFilter: (filter: any) => void
        updateFilterMath: (filter: any) => void
        updateFilter: (filter: any) => void
        removeLocalFilter: (filter: any) => void
        addFilter: () => void
        updateFilterProperty: (filter: any) => void
        setFilters: (filters: any) => void
        setLocalFilters: (filters: any) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'insights', 'ActionFilter', 'entityFilterLogic']
    pathString: 'frontend.src.scenes.insights.ActionFilter.entityFilterLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        selectedFilter: null
        localFilters: any[]
    }
    reducerOptions: any
    reducers: {
        selectedFilter: (state: null, action: any, fullState: any) => null
        localFilters: (state: any[], action: any, fullState: any) => any[]
    }
    selector: (
        state: any
    ) => {
        selectedFilter: null
        localFilters: any[]
    }
    selectors: {
        selectedFilter: (state: any, props: any) => null
        localFilters: (state: any, props: any) => any[]
        eventNames: (state: any, props: any) => string[]
        entities: (state: any, props: any) => { [x: string]: any }
        filters: (state: any, props: any) => { [x: string]: any }
    }
    values: {
        selectedFilter: null
        localFilters: any[]
        eventNames: string[]
        entities: { [x: string]: any }
        filters: { [x: string]: any }
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        entities: (arg1: any, arg2: any) => { [x: string]: any }
        filters: (arg1: any) => { [x: string]: any }
    }
}
