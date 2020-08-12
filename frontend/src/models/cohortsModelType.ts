// Auto-generated with kea-typegen. DO NOT EDIT!

import { Logic, BreakPointFunction } from 'kea'

export interface cohortsModelType extends Logic {
    actionCreators: {
        setPollTimeout: (
            pollTimeout: any
        ) => {
            type: 'set poll timeout (models.cohortsModel)'
            payload: {
                pollTimeout: any
            }
        }
        loadCohorts: () => {
            type: 'load cohorts (models.cohortsModel)'
            payload: any
        }
        loadCohortsSuccess: (
            cohorts: any
        ) => {
            type: 'load cohorts success (models.cohortsModel)'
            payload: {
                cohorts: any
            }
        }
        loadCohortsFailure: (
            error: string
        ) => {
            type: 'load cohorts failure (models.cohortsModel)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'set poll timeout (models.cohortsModel)': 'setPollTimeout'
        'load cohorts (models.cohortsModel)': 'loadCohorts'
        'load cohorts success (models.cohortsModel)': 'loadCohortsSuccess'
        'load cohorts failure (models.cohortsModel)': 'loadCohortsFailure'
    }
    actionTypes: {
        setPollTimeout: 'set poll timeout (models.cohortsModel)'
        loadCohorts: 'load cohorts (models.cohortsModel)'
        loadCohortsSuccess: 'load cohorts success (models.cohortsModel)'
        loadCohortsFailure: 'load cohorts failure (models.cohortsModel)'
    }
    actions: {
        setPollTimeout: (pollTimeout: any) => void
        loadCohorts: () => void
        loadCohortsSuccess: (cohorts: any) => void
        loadCohortsFailure: (error: string) => void
    }
    constants: {}
    defaults: {
        cohorts: any
        cohortsLoading: boolean
        pollTimeout: null
    }
    events: {
        afterMount: () => void
        beforeUnmount: () => void
    }
    key: undefined
    listeners: {
        loadCohortsSuccess: ((
            payload: {
                cohorts: any
            },
            breakpoint: BreakPointFunction,
            action: {
                type: 'load cohorts success (models.cohortsModel)'
                payload: {
                    cohorts: any
                }
            },
            previousState: any
        ) => void | Promise<void>)[]
    }
    path: ['models', 'cohortsModel']
    pathString: 'models.cohortsModel'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        cohorts: any
        cohortsLoading: boolean
        pollTimeout: null
    }
    reducerOptions: {}
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
    sharedListeners: {}
    values: {
        cohorts: any
        cohortsLoading: boolean
        pollTimeout: null
    }
    _isKea: true
    _isKeaWithKey: false
}
