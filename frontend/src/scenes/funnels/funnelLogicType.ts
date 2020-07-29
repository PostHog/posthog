// Auto-generated with kea-typegen. DO NOT EDIT!

export interface funnelLogicType {
    key: any
    actionCreators: {
        setFunnel: (
            funnel: any,
            update: any
        ) => {
            type: 'set funnel (scenes.funnels.funnelLogic)'
            payload: { funnel: any; update: any }
        }
        loadFunnel: (
            id?: any
        ) => {
            type: 'load funnel (scenes.funnels.funnelLogic)'
            payload: any
        }
        loadFunnelSuccess: (funnel: {
            filters: {}
        }) => {
            type: 'load funnel success (scenes.funnels.funnelLogic)'
            payload: {
                funnel: {
                    filters: {}
                }
            }
        }
        loadFunnelFailure: (
            error: string
        ) => {
            type: 'load funnel failure (scenes.funnels.funnelLogic)'
            payload: {
                error: string
            }
        }
        updateFunnel: (
            funnel: any
        ) => {
            type: 'update funnel (scenes.funnels.funnelLogic)'
            payload: any
        }
        updateFunnelSuccess: (funnel: {
            filters: {}
        }) => {
            type: 'update funnel success (scenes.funnels.funnelLogic)'
            payload: {
                funnel: {
                    filters: {}
                }
            }
        }
        updateFunnelFailure: (
            error: string
        ) => {
            type: 'update funnel failure (scenes.funnels.funnelLogic)'
            payload: {
                error: string
            }
        }
        createFunnel: (
            funnel: any
        ) => {
            type: 'create funnel (scenes.funnels.funnelLogic)'
            payload: any
        }
        createFunnelSuccess: (funnel: {
            filters: {}
        }) => {
            type: 'create funnel success (scenes.funnels.funnelLogic)'
            payload: {
                funnel: {
                    filters: {}
                }
            }
        }
        createFunnelFailure: (
            error: string
        ) => {
            type: 'create funnel failure (scenes.funnels.funnelLogic)'
            payload: {
                error: string
            }
        }
        loadStepsWithCount: ({
            id,
            refresh,
        }: any) => {
            type: 'load steps with count (scenes.funnels.funnelLogic)'
            payload: any
        }
        loadStepsWithCountSuccess: (
            stepsWithCount: any
        ) => {
            type: 'load steps with count success (scenes.funnels.funnelLogic)'
            payload: {
                stepsWithCount: any
            }
        }
        loadStepsWithCountFailure: (
            error: string
        ) => {
            type: 'load steps with count failure (scenes.funnels.funnelLogic)'
            payload: {
                error: string
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
        'set funnel (scenes.funnels.funnelLogic)': 'setFunnel'
        'load funnel (scenes.funnels.funnelLogic)': 'loadFunnel'
        'load funnel success (scenes.funnels.funnelLogic)': 'loadFunnelSuccess'
        'load funnel failure (scenes.funnels.funnelLogic)': 'loadFunnelFailure'
        'update funnel (scenes.funnels.funnelLogic)': 'updateFunnel'
        'update funnel success (scenes.funnels.funnelLogic)': 'updateFunnelSuccess'
        'update funnel failure (scenes.funnels.funnelLogic)': 'updateFunnelFailure'
        'create funnel (scenes.funnels.funnelLogic)': 'createFunnel'
        'create funnel success (scenes.funnels.funnelLogic)': 'createFunnelSuccess'
        'create funnel failure (scenes.funnels.funnelLogic)': 'createFunnelFailure'
        'load steps with count (scenes.funnels.funnelLogic)': 'loadStepsWithCount'
        'load steps with count success (scenes.funnels.funnelLogic)': 'loadStepsWithCountSuccess'
        'load steps with count failure (scenes.funnels.funnelLogic)': 'loadStepsWithCountFailure'
        'load people (scenes.funnels.funnelLogic)': 'loadPeople'
        'load people success (scenes.funnels.funnelLogic)': 'loadPeopleSuccess'
        'load people failure (scenes.funnels.funnelLogic)': 'loadPeopleFailure'
    }
    actionTypes: {
        setFunnel: 'set funnel (scenes.funnels.funnelLogic)'
        loadFunnel: 'load funnel (scenes.funnels.funnelLogic)'
        loadFunnelSuccess: 'load funnel success (scenes.funnels.funnelLogic)'
        loadFunnelFailure: 'load funnel failure (scenes.funnels.funnelLogic)'
        updateFunnel: 'update funnel (scenes.funnels.funnelLogic)'
        updateFunnelSuccess: 'update funnel success (scenes.funnels.funnelLogic)'
        updateFunnelFailure: 'update funnel failure (scenes.funnels.funnelLogic)'
        createFunnel: 'create funnel (scenes.funnels.funnelLogic)'
        createFunnelSuccess: 'create funnel success (scenes.funnels.funnelLogic)'
        createFunnelFailure: 'create funnel failure (scenes.funnels.funnelLogic)'
        loadStepsWithCount: 'load steps with count (scenes.funnels.funnelLogic)'
        loadStepsWithCountSuccess: 'load steps with count success (scenes.funnels.funnelLogic)'
        loadStepsWithCountFailure: 'load steps with count failure (scenes.funnels.funnelLogic)'
        loadPeople: 'load people (scenes.funnels.funnelLogic)'
        loadPeopleSuccess: 'load people success (scenes.funnels.funnelLogic)'
        loadPeopleFailure: 'load people failure (scenes.funnels.funnelLogic)'
    }
    actions: {
        setFunnel: (
            funnel: any,
            update: any
        ) => {
            type: 'set funnel (scenes.funnels.funnelLogic)'
            payload: { funnel: any; update: any }
        }
        loadFunnel: (
            id?: any
        ) => {
            type: 'load funnel (scenes.funnels.funnelLogic)'
            payload: any
        }
        loadFunnelSuccess: (funnel: {
            filters: {}
        }) => {
            type: 'load funnel success (scenes.funnels.funnelLogic)'
            payload: {
                funnel: {
                    filters: {}
                }
            }
        }
        loadFunnelFailure: (
            error: string
        ) => {
            type: 'load funnel failure (scenes.funnels.funnelLogic)'
            payload: {
                error: string
            }
        }
        updateFunnel: (
            funnel: any
        ) => {
            type: 'update funnel (scenes.funnels.funnelLogic)'
            payload: any
        }
        updateFunnelSuccess: (funnel: {
            filters: {}
        }) => {
            type: 'update funnel success (scenes.funnels.funnelLogic)'
            payload: {
                funnel: {
                    filters: {}
                }
            }
        }
        updateFunnelFailure: (
            error: string
        ) => {
            type: 'update funnel failure (scenes.funnels.funnelLogic)'
            payload: {
                error: string
            }
        }
        createFunnel: (
            funnel: any
        ) => {
            type: 'create funnel (scenes.funnels.funnelLogic)'
            payload: any
        }
        createFunnelSuccess: (funnel: {
            filters: {}
        }) => {
            type: 'create funnel success (scenes.funnels.funnelLogic)'
            payload: {
                funnel: {
                    filters: {}
                }
            }
        }
        createFunnelFailure: (
            error: string
        ) => {
            type: 'create funnel failure (scenes.funnels.funnelLogic)'
            payload: {
                error: string
            }
        }
        loadStepsWithCount: ({
            id,
            refresh,
        }: any) => {
            type: 'load steps with count (scenes.funnels.funnelLogic)'
            payload: any
        }
        loadStepsWithCountSuccess: (
            stepsWithCount: any
        ) => {
            type: 'load steps with count success (scenes.funnels.funnelLogic)'
            payload: {
                stepsWithCount: any
            }
        }
        loadStepsWithCountFailure: (
            error: string
        ) => {
            type: 'load steps with count failure (scenes.funnels.funnelLogic)'
            payload: {
                error: string
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
