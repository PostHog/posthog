// Auto-generated with kea-typegen. DO NOT EDIT!

export interface annotationsLogicType {
    key: any
    actionCreators: {
        createAnnotation: (
            content: any,
            date_marker: any,
            apply_all?: any
        ) => {
            type: 'create annotation (frontend.src.lib.components.Annotations.annotationsLogic)'
            payload: { content: any; date_marker: any; created_at: Moment; apply_all: boolean }
        }
        createAnnotationNow: (
            content: any,
            date_marker: any,
            apply_all?: any
        ) => {
            type: 'create annotation now (frontend.src.lib.components.Annotations.annotationsLogic)'
            payload: { content: any; date_marker: any; created_at: Moment; apply_all: boolean }
        }
        deleteAnnotation: (
            id: any
        ) => {
            type: 'delete annotation (frontend.src.lib.components.Annotations.annotationsLogic)'
            payload: { id: any }
        }
        clearAnnotationsToCreate: () => {
            type: 'clear annotations to create (frontend.src.lib.components.Annotations.annotationsLogic)'
            payload: {
                value: boolean
            }
        }
        updateDiffType: (
            dates: any
        ) => {
            type: 'update diff type (frontend.src.lib.components.Annotations.annotationsLogic)'
            payload: { dates: any }
        }
        setDiffType: (
            type: any
        ) => {
            type: 'set diff type (frontend.src.lib.components.Annotations.annotationsLogic)'
            payload: { type: any }
        }
        loadAnnotations: ({
            before,
            after,
        }: any) => {
            type: 'load annotations (frontend.src.lib.components.Annotations.annotationsLogic)'
            payload: any
        }
        loadAnnotationsSuccess: (
            annotations: never[]
        ) => {
            type: 'load annotations success (frontend.src.lib.components.Annotations.annotationsLogic)'
            payload: {
                annotations: never[]
            }
        }
        loadAnnotationsFailure: (
            error: string
        ) => {
            type: 'load annotations failure (frontend.src.lib.components.Annotations.annotationsLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'create annotation (frontend.src.lib.components.Annotations.annotationsLogic)': 'createAnnotation'
        'create annotation now (frontend.src.lib.components.Annotations.annotationsLogic)': 'createAnnotationNow'
        'delete annotation (frontend.src.lib.components.Annotations.annotationsLogic)': 'deleteAnnotation'
        'clear annotations to create (frontend.src.lib.components.Annotations.annotationsLogic)': 'clearAnnotationsToCreate'
        'update diff type (frontend.src.lib.components.Annotations.annotationsLogic)': 'updateDiffType'
        'set diff type (frontend.src.lib.components.Annotations.annotationsLogic)': 'setDiffType'
        'load annotations (frontend.src.lib.components.Annotations.annotationsLogic)': 'loadAnnotations'
        'load annotations success (frontend.src.lib.components.Annotations.annotationsLogic)': 'loadAnnotationsSuccess'
        'load annotations failure (frontend.src.lib.components.Annotations.annotationsLogic)': 'loadAnnotationsFailure'
    }
    actionTypes: {
        createAnnotation: 'create annotation (frontend.src.lib.components.Annotations.annotationsLogic)'
        createAnnotationNow: 'create annotation now (frontend.src.lib.components.Annotations.annotationsLogic)'
        deleteAnnotation: 'delete annotation (frontend.src.lib.components.Annotations.annotationsLogic)'
        clearAnnotationsToCreate: 'clear annotations to create (frontend.src.lib.components.Annotations.annotationsLogic)'
        updateDiffType: 'update diff type (frontend.src.lib.components.Annotations.annotationsLogic)'
        setDiffType: 'set diff type (frontend.src.lib.components.Annotations.annotationsLogic)'
        loadAnnotations: 'load annotations (frontend.src.lib.components.Annotations.annotationsLogic)'
        loadAnnotationsSuccess: 'load annotations success (frontend.src.lib.components.Annotations.annotationsLogic)'
        loadAnnotationsFailure: 'load annotations failure (frontend.src.lib.components.Annotations.annotationsLogic)'
    }
    actions: {
        createAnnotation: (content: any, date_marker: any, apply_all?: any) => void
        createAnnotationNow: (content: any, date_marker: any, apply_all?: any) => void
        deleteAnnotation: (id: any) => void
        clearAnnotationsToCreate: () => void
        updateDiffType: (dates: any) => void
        setDiffType: (type: any) => void
        loadAnnotations: ({ before, after }: any) => void
        loadAnnotationsSuccess: (annotations: never[]) => void
        loadAnnotationsFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'lib', 'components', 'Annotations', 'annotationsLogic']
    pathString: 'frontend.src.lib.components.Annotations.annotationsLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        annotations: never[]
        annotationsLoading: boolean
        annotationsToCreate: never[]
        diffType: string
    }
    reducerOptions: any
    reducers: {
        annotations: (state: never[], action: any, fullState: any) => never[]
        annotationsLoading: (state: boolean, action: any, fullState: any) => boolean
        annotationsToCreate: (state: never[], action: any, fullState: any) => never[]
        diffType: (state: string, action: any, fullState: any) => string
    }
    selector: (
        state: any
    ) => {
        annotations: never[]
        annotationsLoading: boolean
        annotationsToCreate: never[]
        diffType: string
    }
    selectors: {
        annotations: (state: any, props: any) => never[]
        annotationsLoading: (state: any, props: any) => boolean
        annotationsToCreate: (state: any, props: any) => never[]
        diffType: (state: any, props: any) => string
        annotationsList: (state: any, props: any) => any[]
        groupedAnnotations: (state: any, props: any) => Dictionary<any[]>
    }
    values: {
        annotations: never[]
        annotationsLoading: boolean
        annotationsToCreate: never[]
        diffType: string
        annotationsList: any[]
        groupedAnnotations: Dictionary<any[]>
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        annotationsList: (arg1: any, arg2: any, arg3: any) => any[]
        groupedAnnotations: (arg1: any, arg2: any) => Dictionary<any[]>
    }
}
