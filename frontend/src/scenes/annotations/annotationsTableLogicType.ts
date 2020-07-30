// Auto-generated with kea-typegen. DO NOT EDIT!

export interface annotationsTableLogicType {
    key: any
    actionCreators: {
        loadAnnotations: () => {
            type: 'load annotations (frontend.src.scenes.annotations.annotationsTableLogic)'
            payload: any
        }
        loadAnnotationsSuccess: (
            annotations: never[]
        ) => {
            type: 'load annotations success (frontend.src.scenes.annotations.annotationsTableLogic)'
            payload: {
                annotations: never[]
            }
        }
        loadAnnotationsFailure: (
            error: string
        ) => {
            type: 'load annotations failure (frontend.src.scenes.annotations.annotationsTableLogic)'
            payload: {
                error: string
            }
        }
        updateAnnotation: (
            id: any,
            content: any
        ) => {
            type: 'update annotation (frontend.src.scenes.annotations.annotationsTableLogic)'
            payload: { id: any; content: any }
        }
        deleteAnnotation: (
            id: any
        ) => {
            type: 'delete annotation (frontend.src.scenes.annotations.annotationsTableLogic)'
            payload: { id: any }
        }
        restoreAnnotation: (
            id: any
        ) => {
            type: 'restore annotation (frontend.src.scenes.annotations.annotationsTableLogic)'
            payload: { id: any }
        }
        loadAnnotationsNext: () => {
            type: 'load annotations next (frontend.src.scenes.annotations.annotationsTableLogic)'
            payload: boolean
        }
        setNext: (
            next: any
        ) => {
            type: 'set next (frontend.src.scenes.annotations.annotationsTableLogic)'
            payload: { next: any }
        }
        appendAnnotations: (
            annotations: any
        ) => {
            type: 'append annotations (frontend.src.scenes.annotations.annotationsTableLogic)'
            payload: { annotations: any }
        }
    }
    actionKeys: {
        'load annotations (frontend.src.scenes.annotations.annotationsTableLogic)': 'loadAnnotations'
        'load annotations success (frontend.src.scenes.annotations.annotationsTableLogic)': 'loadAnnotationsSuccess'
        'load annotations failure (frontend.src.scenes.annotations.annotationsTableLogic)': 'loadAnnotationsFailure'
        'update annotation (frontend.src.scenes.annotations.annotationsTableLogic)': 'updateAnnotation'
        'delete annotation (frontend.src.scenes.annotations.annotationsTableLogic)': 'deleteAnnotation'
        'restore annotation (frontend.src.scenes.annotations.annotationsTableLogic)': 'restoreAnnotation'
        'load annotations next (frontend.src.scenes.annotations.annotationsTableLogic)': 'loadAnnotationsNext'
        'set next (frontend.src.scenes.annotations.annotationsTableLogic)': 'setNext'
        'append annotations (frontend.src.scenes.annotations.annotationsTableLogic)': 'appendAnnotations'
    }
    actionTypes: {
        loadAnnotations: 'load annotations (frontend.src.scenes.annotations.annotationsTableLogic)'
        loadAnnotationsSuccess: 'load annotations success (frontend.src.scenes.annotations.annotationsTableLogic)'
        loadAnnotationsFailure: 'load annotations failure (frontend.src.scenes.annotations.annotationsTableLogic)'
        updateAnnotation: 'update annotation (frontend.src.scenes.annotations.annotationsTableLogic)'
        deleteAnnotation: 'delete annotation (frontend.src.scenes.annotations.annotationsTableLogic)'
        restoreAnnotation: 'restore annotation (frontend.src.scenes.annotations.annotationsTableLogic)'
        loadAnnotationsNext: 'load annotations next (frontend.src.scenes.annotations.annotationsTableLogic)'
        setNext: 'set next (frontend.src.scenes.annotations.annotationsTableLogic)'
        appendAnnotations: 'append annotations (frontend.src.scenes.annotations.annotationsTableLogic)'
    }
    actions: {
        loadAnnotations: () => void
        loadAnnotationsSuccess: (annotations: never[]) => void
        loadAnnotationsFailure: (error: string) => void
        updateAnnotation: (id: any, content: any) => void
        deleteAnnotation: (id: any) => void
        restoreAnnotation: (id: any) => void
        loadAnnotationsNext: () => void
        setNext: (next: any) => void
        appendAnnotations: (annotations: any) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'annotations', 'annotationsTableLogic']
    pathString: 'frontend.src.scenes.annotations.annotationsTableLogic'
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
