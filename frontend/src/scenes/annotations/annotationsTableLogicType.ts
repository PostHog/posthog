// Auto-generated with kea-typegen. DO NOT EDIT!

export interface annotationsTableLogicType {
    key: any
    actionCreators: {
        loadAnnotations: () => {
            type: 'load annotations (scenes.annotations.annotationsTableLogic)'
            payload: any
        }
        loadAnnotationsSuccess: (
            annotations: never[]
        ) => {
            type: 'load annotations success (scenes.annotations.annotationsTableLogic)'
            payload: {
                annotations: never[]
            }
        }
        loadAnnotationsFailure: (
            error: string
        ) => {
            type: 'load annotations failure (scenes.annotations.annotationsTableLogic)'
            payload: {
                error: string
            }
        }
        updateAnnotation: (
            id: any,
            content: any
        ) => {
            type: 'update annotation (scenes.annotations.annotationsTableLogic)'
            payload: { id: any; content: any }
        }
        deleteAnnotation: (
            id: any
        ) => {
            type: 'delete annotation (scenes.annotations.annotationsTableLogic)'
            payload: { id: any }
        }
        loadAnnotationsNext: () => {
            type: 'load annotations next (scenes.annotations.annotationsTableLogic)'
            payload: boolean
        }
        setNext: (
            next: any
        ) => {
            type: 'set next (scenes.annotations.annotationsTableLogic)'
            payload: { next: any }
        }
        appendAnnotations: (
            annotations: any
        ) => {
            type: 'append annotations (scenes.annotations.annotationsTableLogic)'
            payload: { annotations: any }
        }
    }
    actionKeys: {
        'load annotations (scenes.annotations.annotationsTableLogic)': 'loadAnnotations'
        'load annotations success (scenes.annotations.annotationsTableLogic)': 'loadAnnotationsSuccess'
        'load annotations failure (scenes.annotations.annotationsTableLogic)': 'loadAnnotationsFailure'
        'update annotation (scenes.annotations.annotationsTableLogic)': 'updateAnnotation'
        'delete annotation (scenes.annotations.annotationsTableLogic)': 'deleteAnnotation'
        'load annotations next (scenes.annotations.annotationsTableLogic)': 'loadAnnotationsNext'
        'set next (scenes.annotations.annotationsTableLogic)': 'setNext'
        'append annotations (scenes.annotations.annotationsTableLogic)': 'appendAnnotations'
    }
    actionTypes: {
        loadAnnotations: 'load annotations (scenes.annotations.annotationsTableLogic)'
        loadAnnotationsSuccess: 'load annotations success (scenes.annotations.annotationsTableLogic)'
        loadAnnotationsFailure: 'load annotations failure (scenes.annotations.annotationsTableLogic)'
        updateAnnotation: 'update annotation (scenes.annotations.annotationsTableLogic)'
        deleteAnnotation: 'delete annotation (scenes.annotations.annotationsTableLogic)'
        loadAnnotationsNext: 'load annotations next (scenes.annotations.annotationsTableLogic)'
        setNext: 'set next (scenes.annotations.annotationsTableLogic)'
        appendAnnotations: 'append annotations (scenes.annotations.annotationsTableLogic)'
    }
    actions: {
        loadAnnotations: () => {
            type: 'load annotations (scenes.annotations.annotationsTableLogic)'
            payload: any
        }
        loadAnnotationsSuccess: (
            annotations: never[]
        ) => {
            type: 'load annotations success (scenes.annotations.annotationsTableLogic)'
            payload: {
                annotations: never[]
            }
        }
        loadAnnotationsFailure: (
            error: string
        ) => {
            type: 'load annotations failure (scenes.annotations.annotationsTableLogic)'
            payload: {
                error: string
            }
        }
        updateAnnotation: (
            id: any,
            content: any
        ) => {
            type: 'update annotation (scenes.annotations.annotationsTableLogic)'
            payload: { id: any; content: any }
        }
        deleteAnnotation: (
            id: any
        ) => {
            type: 'delete annotation (scenes.annotations.annotationsTableLogic)'
            payload: { id: any }
        }
        loadAnnotationsNext: () => {
            type: 'load annotations next (scenes.annotations.annotationsTableLogic)'
            payload: boolean
        }
        setNext: (
            next: any
        ) => {
            type: 'set next (scenes.annotations.annotationsTableLogic)'
            payload: { next: any }
        }
        appendAnnotations: (
            annotations: any
        ) => {
            type: 'append annotations (scenes.annotations.annotationsTableLogic)'
            payload: { annotations: any }
        }
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['scenes', 'annotations', 'annotationsTableLogic']
    pathString: 'scenes.annotations.annotationsTableLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        annotations: never[]
        annotationsLoading: boolean
        next: null
        loadingNext: boolean
    }
    reducerOptions: any
    reducers: {
        annotations: (state: never[], action: any, fullState: any) => never[]
        annotationsLoading: (state: boolean, action: any, fullState: any) => boolean
        next: (state: null, action: any, fullState: any) => null
        loadingNext: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        annotations: never[]
        annotationsLoading: boolean
        next: null
        loadingNext: boolean
    }
    selectors: {
        annotations: (state: any, props: any) => never[]
        annotationsLoading: (state: any, props: any) => boolean
        next: (state: any, props: any) => null
        loadingNext: (state: any, props: any) => boolean
    }
    values: {
        annotations: never[]
        annotationsLoading: boolean
        next: null
        loadingNext: boolean
    }
    _isKea: true
}
