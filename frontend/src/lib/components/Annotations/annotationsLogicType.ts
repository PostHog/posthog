// Auto-generated with kea-typegen. DO NOT EDIT!

export interface annotationsLogicType {
    key: string
    actionCreators: {
        createAnnotation: (
            content: any,
            date_marker: any,
            apply_all?: any
        ) => {
            type: 'create annotation (lib.components.Annotations.annotationsLogic)'
            payload: { content: any; date_marker: any; created_at: Moment; apply_all: boolean }
        }
        createAnnotationNow: (
            content: any,
            date_marker: any,
            apply_all?: any
        ) => {
            type: 'create annotation now (lib.components.Annotations.annotationsLogic)'
            payload: { content: any; date_marker: any; created_at: Moment; apply_all: boolean }
        }
        deleteAnnotation: (
            id: any
        ) => {
            type: 'delete annotation (lib.components.Annotations.annotationsLogic)'
            payload: { id: any }
        }
        clearAnnotationsToCreate: () => {
            type: 'clear annotations to create (lib.components.Annotations.annotationsLogic)'
            payload: {
                value: boolean
            }
        }
        updateDiffType: (
            dates: any
        ) => {
            type: 'update diff type (lib.components.Annotations.annotationsLogic)'
            payload: { dates: any }
        }
        setDiffType: (
            type: any
        ) => {
            type: 'set diff type (lib.components.Annotations.annotationsLogic)'
            payload: { type: any }
        }
        loadAnnotations: ({
            before,
            after,
        }: any) => {
            type: 'load annotations (lib.components.Annotations.annotationsLogic)'
            payload: any
        }
        loadAnnotationsSuccess: (
            annotations: any[]
        ) => {
            type: 'load annotations success (lib.components.Annotations.annotationsLogic)'
            payload: {
                annotations: any[]
            }
        }
        loadAnnotationsFailure: (
            error: string
        ) => {
            type: 'load annotations failure (lib.components.Annotations.annotationsLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'create annotation (lib.components.Annotations.annotationsLogic)': 'createAnnotation'
        'create annotation now (lib.components.Annotations.annotationsLogic)': 'createAnnotationNow'
        'delete annotation (lib.components.Annotations.annotationsLogic)': 'deleteAnnotation'
        'clear annotations to create (lib.components.Annotations.annotationsLogic)': 'clearAnnotationsToCreate'
        'update diff type (lib.components.Annotations.annotationsLogic)': 'updateDiffType'
        'set diff type (lib.components.Annotations.annotationsLogic)': 'setDiffType'
        'load annotations (lib.components.Annotations.annotationsLogic)': 'loadAnnotations'
        'load annotations success (lib.components.Annotations.annotationsLogic)': 'loadAnnotationsSuccess'
        'load annotations failure (lib.components.Annotations.annotationsLogic)': 'loadAnnotationsFailure'
    }
    actionTypes: {
        createAnnotation: 'create annotation (lib.components.Annotations.annotationsLogic)'
        createAnnotationNow: 'create annotation now (lib.components.Annotations.annotationsLogic)'
        deleteAnnotation: 'delete annotation (lib.components.Annotations.annotationsLogic)'
        clearAnnotationsToCreate: 'clear annotations to create (lib.components.Annotations.annotationsLogic)'
        updateDiffType: 'update diff type (lib.components.Annotations.annotationsLogic)'
        setDiffType: 'set diff type (lib.components.Annotations.annotationsLogic)'
        loadAnnotations: 'load annotations (lib.components.Annotations.annotationsLogic)'
        loadAnnotationsSuccess: 'load annotations success (lib.components.Annotations.annotationsLogic)'
        loadAnnotationsFailure: 'load annotations failure (lib.components.Annotations.annotationsLogic)'
    }
    actions: {
        createAnnotation: (content: any, date_marker: any, apply_all?: any) => void
        createAnnotationNow: (content: any, date_marker: any, apply_all?: any) => void
        deleteAnnotation: (id: any) => void
        clearAnnotationsToCreate: () => void
        updateDiffType: (dates: any) => void
        setDiffType: (type: any) => void
        loadAnnotations: ({ before, after }: any) => void
        loadAnnotationsSuccess: (annotations: any[]) => void
        loadAnnotationsFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: {
        annotations: any[]
        annotationsLoading: boolean
        annotationsToCreate: any[]
        diffType: string
    }
    events: any
    path: ['lib', 'components', 'Annotations', 'annotationsLogic']
    pathString: 'lib.components.Annotations.annotationsLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        annotations: any[]
        annotationsLoading: boolean
        annotationsToCreate: any[]
        diffType: string
    }
    reducerOptions: any
    reducers: {
        annotations: (state: any[], action: any, fullState: any) => any[]
        annotationsLoading: (state: boolean, action: any, fullState: any) => boolean
        annotationsToCreate: (state: any[], action: any, fullState: any) => any[]
        diffType: (state: string, action: any, fullState: any) => string
    }
    selector: (
        state: any
    ) => {
        annotations: any[]
        annotationsLoading: boolean
        annotationsToCreate: any[]
        diffType: string
    }
    selectors: {
        annotations: (state: any, props: any) => any[]
        annotationsLoading: (state: any, props: any) => boolean
        annotationsToCreate: (state: any, props: any) => any[]
        diffType: (state: any, props: any) => string
        annotationsList: (state: any, props: any) => any[]
        groupedAnnotations: (state: any, props: any) => Dictionary<any[]>
    }
    values: {
        annotations: any[]
        annotationsLoading: boolean
        annotationsToCreate: any[]
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
