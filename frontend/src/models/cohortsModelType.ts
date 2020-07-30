// Auto-generated with kea-typegen. DO NOT EDIT!

export interface cohortsModelType {
    key: any
    actionCreators: {
        setPollTimeout: (
            pollTimeout: any
        ) => {
            type: 'set poll timeout (frontend.src.models.cohortsModel)'
            payload: { pollTimeout: any }
        }
        loadCohorts: () => {
            type: 'load cohorts (frontend.src.models.cohortsModel)'
            payload: any
        }
        loadCohortsSuccess: (
            cohorts: any
        ) => {
            type: 'load cohorts success (frontend.src.models.cohortsModel)'
            payload: {
                cohorts: any
            }
        }
        loadCohortsFailure: (
            error: string
        ) => {
            type: 'load cohorts failure (frontend.src.models.cohortsModel)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'set poll timeout (frontend.src.models.cohortsModel)': 'setPollTimeout'
        'load cohorts (frontend.src.models.cohortsModel)': 'loadCohorts'
        'load cohorts success (frontend.src.models.cohortsModel)': 'loadCohortsSuccess'
        'load cohorts failure (frontend.src.models.cohortsModel)': 'loadCohortsFailure'
    }
    actionTypes: {
        setPollTimeout: 'set poll timeout (frontend.src.models.cohortsModel)'
        loadCohorts: 'load cohorts (frontend.src.models.cohortsModel)'
        loadCohortsSuccess: 'load cohorts success (frontend.src.models.cohortsModel)'
        loadCohortsFailure: 'load cohorts failure (frontend.src.models.cohortsModel)'
    }
    actions: {
        setPollTimeout: (pollTimeout: any) => void
        loadCohorts: () => void
        loadCohortsSuccess: (cohorts: any) => void
        loadCohortsFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'models', 'cohortsModel']
    pathString: 'frontend.src.models.cohortsModel'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        cohorts: any
        cohortsLoading: boolean
        pollTimeout: null
    }
    reducerOptions: any
    reducers: {
        cohorts: (state: any, action: any, fullState: any) => any
        cohortsLoading: (state: boolean, action: any, fullState: any) => boolean
        pollTimeout: (state: null, action: any, fullState: any) => null
    }
    selector: (
        state: any
    ) => {
        cohorts: any
        cohortsLoading: boolean
        pollTimeout: null
    }
    selectors: {
        cohorts: (state: any, props: any) => any
        cohortsLoading: (state: any, props: any) => boolean
        pollTimeout: (state: any, props: any) => null
    }
    values: {
        cohorts: any
        cohortsLoading: boolean
        pollTimeout: null
    }
    _isKea: true
}
