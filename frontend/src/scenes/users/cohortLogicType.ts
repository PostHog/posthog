// Auto-generated with kea-typegen. DO NOT EDIT!

export interface cohortLogicType {
    key: any
    actionCreators: {
        saveCohort: (
            cohort: any
        ) => {
            type: 'save cohort (frontend.src.scenes.users.cohortLogic)'
            payload: { cohort: any }
        }
        setCohort: (
            cohort: any
        ) => {
            type: 'set cohort (frontend.src.scenes.users.cohortLogic)'
            payload: { cohort: any }
        }
        checkIsFinished: (
            cohort: any
        ) => {
            type: 'check is finished (frontend.src.scenes.users.cohortLogic)'
            payload: { cohort: any }
        }
        setToastId: (
            toastId: any
        ) => {
            type: 'set toast id (frontend.src.scenes.users.cohortLogic)'
            payload: { toastId: any }
        }
        setPollTimeout: (
            pollTimeout: any
        ) => {
            type: 'set poll timeout (frontend.src.scenes.users.cohortLogic)'
            payload: { pollTimeout: any }
        }
        loadPersonProperties: () => {
            type: 'load person properties (frontend.src.scenes.users.cohortLogic)'
            payload: any
        }
        loadPersonPropertiesSuccess: (
            personProperties: any
        ) => {
            type: 'load person properties success (frontend.src.scenes.users.cohortLogic)'
            payload: {
                personProperties: any
            }
        }
        loadPersonPropertiesFailure: (
            error: string
        ) => {
            type: 'load person properties failure (frontend.src.scenes.users.cohortLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'save cohort (frontend.src.scenes.users.cohortLogic)': 'saveCohort'
        'set cohort (frontend.src.scenes.users.cohortLogic)': 'setCohort'
        'check is finished (frontend.src.scenes.users.cohortLogic)': 'checkIsFinished'
        'set toast id (frontend.src.scenes.users.cohortLogic)': 'setToastId'
        'set poll timeout (frontend.src.scenes.users.cohortLogic)': 'setPollTimeout'
        'load person properties (frontend.src.scenes.users.cohortLogic)': 'loadPersonProperties'
        'load person properties success (frontend.src.scenes.users.cohortLogic)': 'loadPersonPropertiesSuccess'
        'load person properties failure (frontend.src.scenes.users.cohortLogic)': 'loadPersonPropertiesFailure'
    }
    actionTypes: {
        saveCohort: 'save cohort (frontend.src.scenes.users.cohortLogic)'
        setCohort: 'set cohort (frontend.src.scenes.users.cohortLogic)'
        checkIsFinished: 'check is finished (frontend.src.scenes.users.cohortLogic)'
        setToastId: 'set toast id (frontend.src.scenes.users.cohortLogic)'
        setPollTimeout: 'set poll timeout (frontend.src.scenes.users.cohortLogic)'
        loadPersonProperties: 'load person properties (frontend.src.scenes.users.cohortLogic)'
        loadPersonPropertiesSuccess: 'load person properties success (frontend.src.scenes.users.cohortLogic)'
        loadPersonPropertiesFailure: 'load person properties failure (frontend.src.scenes.users.cohortLogic)'
    }
    actions: {
        saveCohort: (cohort: any) => void
        setCohort: (cohort: any) => void
        checkIsFinished: (cohort: any) => void
        setToastId: (toastId: any) => void
        setPollTimeout: (pollTimeout: any) => void
        loadPersonProperties: () => void
        loadPersonPropertiesSuccess: (personProperties: any) => void
        loadPersonPropertiesFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'users', 'cohortLogic']
    pathString: 'frontend.src.scenes.users.cohortLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        personProperties: any
        personPropertiesLoading: boolean
        pollTimeout: null
        cohort: null
        toastId: null
    }
    reducerOptions: any
    reducers: {
        personProperties: (state: any, action: any, fullState: any) => any
        personPropertiesLoading: (state: boolean, action: any, fullState: any) => boolean
        pollTimeout: (state: null, action: any, fullState: any) => null
        cohort: (state: null, action: any, fullState: any) => null
        toastId: (state: null, action: any, fullState: any) => null
    }
    selector: (
        state: any
    ) => {
        personProperties: any
        personPropertiesLoading: boolean
        pollTimeout: null
        cohort: null
        toastId: null
    }
    selectors: {
        personProperties: (state: any, props: any) => any
        personPropertiesLoading: (state: any, props: any) => boolean
        pollTimeout: (state: any, props: any) => null
        cohort: (state: any, props: any) => null
        toastId: (state: any, props: any) => null
    }
    values: {
        personProperties: any
        personPropertiesLoading: boolean
        pollTimeout: null
        cohort: null
        toastId: null
    }
    _isKea: true
}
