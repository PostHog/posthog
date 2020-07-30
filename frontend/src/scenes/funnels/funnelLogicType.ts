// Auto-generated with kea-typegen. DO NOT EDIT!

export interface funnelLogicType {
    key: any
    actionCreators: {
        setFunnel: (
            funnel: any,
            update: any
        ) => {
            type: 'set funnel (frontend.src.scenes.funnels.funnelLogic)'
            payload: { funnel: any; update: any }
        }
        clearFunnel: () => {
            type: 'clear funnel (frontend.src.scenes.funnels.funnelLogic)'
            payload: {
                value: boolean
            }
        }
        loadFunnel: (
            id?: any
        ) => {
            type: 'load funnel (frontend.src.scenes.funnels.funnelLogic)'
            payload: any
        }
        loadFunnelSuccess: (funnel: {
            filters: {}
        }) => {
            type: 'load funnel success (frontend.src.scenes.funnels.funnelLogic)'
            payload: {
                funnel: {
                    filters: {}
                }
            }
        }
        loadFunnelFailure: (
            error: string
        ) => {
            type: 'load funnel failure (frontend.src.scenes.funnels.funnelLogic)'
            payload: {
                error: string
            }
        }
        updateFunnel: (
            funnel: any
        ) => {
            type: 'update funnel (frontend.src.scenes.funnels.funnelLogic)'
            payload: any
        }
        updateFunnelSuccess: (funnel: {
            filters: {}
        }) => {
            type: 'update funnel success (frontend.src.scenes.funnels.funnelLogic)'
            payload: {
                funnel: {
                    filters: {}
                }
            }
        }
        updateFunnelFailure: (
            error: string
        ) => {
            type: 'update funnel failure (frontend.src.scenes.funnels.funnelLogic)'
            payload: {
                error: string
            }
        }
        createFunnel: (
            funnel: any
        ) => {
            type: 'create funnel (frontend.src.scenes.funnels.funnelLogic)'
            payload: any
        }
        createFunnelSuccess: (funnel: {
            filters: {}
        }) => {
            type: 'create funnel success (frontend.src.scenes.funnels.funnelLogic)'
            payload: {
                funnel: {
                    filters: {}
                }
            }
        }
        createFunnelFailure: (
            error: string
        ) => {
            type: 'create funnel failure (frontend.src.scenes.funnels.funnelLogic)'
            payload: {
                error: string
            }
        }
        loadStepsWithCount: ({
            id,
            refresh,
        }: any) => {
            type: 'load steps with count (frontend.src.scenes.funnels.funnelLogic)'
            payload: any
        }
        loadStepsWithCountSuccess: (
            stepsWithCount: any
        ) => {
            type: 'load steps with count success (frontend.src.scenes.funnels.funnelLogic)'
            payload: {
                stepsWithCount: any
            }
        }
        loadStepsWithCountFailure: (
            error: string
        ) => {
            type: 'load steps with count failure (frontend.src.scenes.funnels.funnelLogic)'
            payload: {
                error: string
            }
        }
        loadPeople: (
            steps: any
        ) => {
            type: 'load people (frontend.src.scenes.funnels.funnelLogic)'
            payload: any
        }
        loadPeopleSuccess: (
            people: any
        ) => {
            type: 'load people success (frontend.src.scenes.funnels.funnelLogic)'
            payload: {
                people: any
            }
        }
        loadPeopleFailure: (
            error: string
        ) => {
            type: 'load people failure (frontend.src.scenes.funnels.funnelLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'set funnel (frontend.src.scenes.funnels.funnelLogic)': 'setFunnel'
        'clear funnel (frontend.src.scenes.funnels.funnelLogic)': 'clearFunnel'
        'load funnel (frontend.src.scenes.funnels.funnelLogic)': 'loadFunnel'
        'load funnel success (frontend.src.scenes.funnels.funnelLogic)': 'loadFunnelSuccess'
        'load funnel failure (frontend.src.scenes.funnels.funnelLogic)': 'loadFunnelFailure'
        'update funnel (frontend.src.scenes.funnels.funnelLogic)': 'updateFunnel'
        'update funnel success (frontend.src.scenes.funnels.funnelLogic)': 'updateFunnelSuccess'
        'update funnel failure (frontend.src.scenes.funnels.funnelLogic)': 'updateFunnelFailure'
        'create funnel (frontend.src.scenes.funnels.funnelLogic)': 'createFunnel'
        'create funnel success (frontend.src.scenes.funnels.funnelLogic)': 'createFunnelSuccess'
        'create funnel failure (frontend.src.scenes.funnels.funnelLogic)': 'createFunnelFailure'
        'load steps with count (frontend.src.scenes.funnels.funnelLogic)': 'loadStepsWithCount'
        'load steps with count success (frontend.src.scenes.funnels.funnelLogic)': 'loadStepsWithCountSuccess'
        'load steps with count failure (frontend.src.scenes.funnels.funnelLogic)': 'loadStepsWithCountFailure'
        'load people (frontend.src.scenes.funnels.funnelLogic)': 'loadPeople'
        'load people success (frontend.src.scenes.funnels.funnelLogic)': 'loadPeopleSuccess'
        'load people failure (frontend.src.scenes.funnels.funnelLogic)': 'loadPeopleFailure'
    }
    actionTypes: {
        setFunnel: 'set funnel (frontend.src.scenes.funnels.funnelLogic)'
        clearFunnel: 'clear funnel (frontend.src.scenes.funnels.funnelLogic)'
        loadFunnel: 'load funnel (frontend.src.scenes.funnels.funnelLogic)'
        loadFunnelSuccess: 'load funnel success (frontend.src.scenes.funnels.funnelLogic)'
        loadFunnelFailure: 'load funnel failure (frontend.src.scenes.funnels.funnelLogic)'
        updateFunnel: 'update funnel (frontend.src.scenes.funnels.funnelLogic)'
        updateFunnelSuccess: 'update funnel success (frontend.src.scenes.funnels.funnelLogic)'
        updateFunnelFailure: 'update funnel failure (frontend.src.scenes.funnels.funnelLogic)'
        createFunnel: 'create funnel (frontend.src.scenes.funnels.funnelLogic)'
        createFunnelSuccess: 'create funnel success (frontend.src.scenes.funnels.funnelLogic)'
        createFunnelFailure: 'create funnel failure (frontend.src.scenes.funnels.funnelLogic)'
        loadStepsWithCount: 'load steps with count (frontend.src.scenes.funnels.funnelLogic)'
        loadStepsWithCountSuccess: 'load steps with count success (frontend.src.scenes.funnels.funnelLogic)'
        loadStepsWithCountFailure: 'load steps with count failure (frontend.src.scenes.funnels.funnelLogic)'
        loadPeople: 'load people (frontend.src.scenes.funnels.funnelLogic)'
        loadPeopleSuccess: 'load people success (frontend.src.scenes.funnels.funnelLogic)'
        loadPeopleFailure: 'load people failure (frontend.src.scenes.funnels.funnelLogic)'
    }
    actions: {
        setFunnel: (funnel: any, update: any) => void
        clearFunnel: () => void
        loadFunnel: (id?: any) => void
        loadFunnelSuccess: (funnel: { filters: {} }) => void
        loadFunnelFailure: (error: string) => void
        updateFunnel: (funnel: any) => void
        updateFunnelSuccess: (funnel: { filters: {} }) => void
        updateFunnelFailure: (error: string) => void
        createFunnel: (funnel: any) => void
        createFunnelSuccess: (funnel: { filters: {} }) => void
        createFunnelFailure: (error: string) => void
        loadStepsWithCount: ({ id, refresh }: any) => void
        loadStepsWithCountSuccess: (stepsWithCount: any) => void
        loadStepsWithCountFailure: (error: string) => void
        loadPeople: (steps: any) => void
        loadPeopleSuccess: (people: any) => void
        loadPeopleFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'funnels', 'funnelLogic']
    pathString: 'frontend.src.scenes.funnels.funnelLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        funnel: {
            filters: {}
        }
        funnelLoading: boolean
        stepsWithCount: any
        stepsWithCountLoading: boolean
        people: any
        peopleLoading: boolean
    }
    reducerOptions: any
    reducers: {
        funnel: (
            state: {
                filters: {}
            },
            action: any,
            fullState: any
        ) => {
            filters: {}
        }
        funnelLoading: (state: boolean, action: any, fullState: any) => boolean
        stepsWithCount: (state: any, action: any, fullState: any) => any
        stepsWithCountLoading: (state: boolean, action: any, fullState: any) => boolean
        people: (state: any, action: any, fullState: any) => any
        peopleLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        funnel: {
            filters: {}
        }
        funnelLoading: boolean
        stepsWithCount: any
        stepsWithCountLoading: boolean
        people: any
        peopleLoading: boolean
    }
    selectors: {
        funnel: (
            state: any,
            props: any
        ) => {
            filters: {}
        }
        funnelLoading: (state: any, props: any) => boolean
        stepsWithCount: (state: any, props: any) => any
        stepsWithCountLoading: (state: any, props: any) => boolean
        people: (state: any, props: any) => any
        peopleLoading: (state: any, props: any) => boolean
        peopleSorted: (state: any, props: any) => any
        isStepsEmpty: (state: any, props: any) => boolean
    }
    values: {
        funnel: {
            filters: {}
        }
        funnelLoading: boolean
        stepsWithCount: any
        stepsWithCountLoading: boolean
        people: any
        peopleLoading: boolean
        peopleSorted: any
        isStepsEmpty: boolean
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        peopleSorted: (arg1: any, arg2: any) => any
        isStepsEmpty: (arg1: any) => boolean
    }
}
