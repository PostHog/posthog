// Auto-generated with kea-typegen. DO NOT EDIT!

export interface funnelLogicType {
    key: any
    actionCreators: {
        setSteps: (
            steps: any
        ) => {
            type: 'set steps (scenes.funnels.funnelLogic)'
            payload: { steps: any }
        }
        clearFunnel: () => {
            type: 'clear funnel (scenes.funnels.funnelLogic)'
            payload: {
                value: boolean
            }
        }
        setFilters: (
            filters: any,
            refresh?: any
        ) => {
            type: 'set filters (scenes.funnels.funnelLogic)'
            payload: { filters: any; refresh: boolean }
        }
        loadFunnel: () => {
            type: 'load funnel (scenes.funnels.funnelLogic)'
            payload: {
                value: boolean
            }
        }
        createInsight: (
            filters: Record<string, any>
        ) => {
            type: 'create insight (scenes.funnels.funnelLogic)'
            payload: {
                filters: Record<string, any>
            }
        }
        loadPeople: (
            steps: any
        ) => {
            type: 'load people (scenes.funnels.funnelLogic)'
            payload: any
        }
        loadPeopleSuccess: (
            people: any
        ) => {
            type: 'load people success (scenes.funnels.funnelLogic)'
            payload: {
                people: any
            }
        }
        loadPeopleFailure: (
            error: string
        ) => {
            type: 'load people failure (scenes.funnels.funnelLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'set steps (scenes.funnels.funnelLogic)': 'setSteps'
        'clear funnel (scenes.funnels.funnelLogic)': 'clearFunnel'
        'set filters (scenes.funnels.funnelLogic)': 'setFilters'
        'load funnel (scenes.funnels.funnelLogic)': 'loadFunnel'
        'create insight (scenes.funnels.funnelLogic)': 'createInsight'
        'load people (scenes.funnels.funnelLogic)': 'loadPeople'
        'load people success (scenes.funnels.funnelLogic)': 'loadPeopleSuccess'
        'load people failure (scenes.funnels.funnelLogic)': 'loadPeopleFailure'
    }
    actionTypes: {
        setSteps: 'set steps (scenes.funnels.funnelLogic)'
        clearFunnel: 'clear funnel (scenes.funnels.funnelLogic)'
        setFilters: 'set filters (scenes.funnels.funnelLogic)'
        loadFunnel: 'load funnel (scenes.funnels.funnelLogic)'
        createInsight: 'create insight (scenes.funnels.funnelLogic)'
        loadPeople: 'load people (scenes.funnels.funnelLogic)'
        loadPeopleSuccess: 'load people success (scenes.funnels.funnelLogic)'
        loadPeopleFailure: 'load people failure (scenes.funnels.funnelLogic)'
    }
    actions: {
        setSteps: (steps: any) => void
        clearFunnel: () => void
        setFilters: (filters: any, refresh?: any) => void
        loadFunnel: () => void
        createInsight: (filters: Record<string, any>) => void
        loadPeople: (steps: any) => void
        loadPeopleSuccess: (people: any) => void
        loadPeopleFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['scenes', 'funnels', 'funnelLogic']
    pathString: 'scenes.funnels.funnelLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        people: any
        peopleLoading: boolean
        filters: {}
        stepsWithCount: null
        stepsWithCountLoading: boolean
    }
    reducerOptions: any
    reducers: {
        people: (state: any, action: any, fullState: any) => any
        peopleLoading: (state: boolean, action: any, fullState: any) => boolean
        filters: (state: {}, action: any, fullState: any) => {}
        stepsWithCount: (state: null, action: any, fullState: any) => null
        stepsWithCountLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        people: any
        peopleLoading: boolean
        filters: {}
        stepsWithCount: null
        stepsWithCountLoading: boolean
    }
    selectors: {
        people: (state: any, props: any) => any
        peopleLoading: (state: any, props: any) => boolean
        filters: (state: any, props: any) => {}
        stepsWithCount: (state: any, props: any) => null
        stepsWithCountLoading: (state: any, props: any) => boolean
        peopleSorted: (state: any, props: any) => any
        isStepsEmpty: (state: any, props: any) => boolean
        propertiesForUrl: (
            state: any,
            props: any
        ) => { properties?: any; events?: any; actions?: any; date_to?: any; date_from?: any; insight: string }
    }
    values: {
        people: any
        peopleLoading: boolean
        filters: {}
        stepsWithCount: null
        stepsWithCountLoading: boolean
        peopleSorted: any
        isStepsEmpty: boolean
        propertiesForUrl: {
            properties?: any
            events?: any
            actions?: any
            date_to?: any
            date_from?: any
            insight: string
        }
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        peopleSorted: (arg1: any, arg2: any) => any
        isStepsEmpty: (arg1: any) => boolean
        propertiesForUrl: (
            arg1: any
        ) => { properties?: any; events?: any; actions?: any; date_to?: any; date_from?: any; insight: string }
    }
}
