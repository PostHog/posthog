// Auto-generated with kea-typegen. DO NOT EDIT!

export interface annotationsModelType {
    key: any
    actionCreators: {
        createGlobalAnnotation: (
            content: any,
            date_marker: any,
            dashboard_item: any
        ) => {
            type: 'create global annotation (frontend.src.models.annotationsModel)'
            payload: { content: any; date_marker: any; created_at: Moment; dashboard_item: any }
        }
        deleteGlobalAnnotation: (
            id: any
        ) => {
            type: 'delete global annotation (frontend.src.models.annotationsModel)'
            payload: { id: any }
        }
        loadGlobalAnnotations: () => {
            type: 'load global annotations (frontend.src.models.annotationsModel)'
            payload: any
        }
        loadGlobalAnnotationsSuccess: (
            globalAnnotations: never[]
        ) => {
            type: 'load global annotations success (frontend.src.models.annotationsModel)'
            payload: {
                globalAnnotations: never[]
            }
        }
        loadGlobalAnnotationsFailure: (
            error: string
        ) => {
            type: 'load global annotations failure (frontend.src.models.annotationsModel)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'create global annotation (frontend.src.models.annotationsModel)': 'createGlobalAnnotation'
        'delete global annotation (frontend.src.models.annotationsModel)': 'deleteGlobalAnnotation'
        'load global annotations (frontend.src.models.annotationsModel)': 'loadGlobalAnnotations'
        'load global annotations success (frontend.src.models.annotationsModel)': 'loadGlobalAnnotationsSuccess'
        'load global annotations failure (frontend.src.models.annotationsModel)': 'loadGlobalAnnotationsFailure'
    }
    actionTypes: {
        createGlobalAnnotation: 'create global annotation (frontend.src.models.annotationsModel)'
        deleteGlobalAnnotation: 'delete global annotation (frontend.src.models.annotationsModel)'
        loadGlobalAnnotations: 'load global annotations (frontend.src.models.annotationsModel)'
        loadGlobalAnnotationsSuccess: 'load global annotations success (frontend.src.models.annotationsModel)'
        loadGlobalAnnotationsFailure: 'load global annotations failure (frontend.src.models.annotationsModel)'
    }
    actions: {
        createGlobalAnnotation: (content: any, date_marker: any, dashboard_item: any) => void
        deleteGlobalAnnotation: (id: any) => void
        loadGlobalAnnotations: () => void
        loadGlobalAnnotationsSuccess: (globalAnnotations: never[]) => void
        loadGlobalAnnotationsFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'models', 'annotationsModel']
    pathString: 'frontend.src.models.annotationsModel'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        globalAnnotations: never[]
        globalAnnotationsLoading: boolean
    }
    reducerOptions: any
    reducers: {
        globalAnnotations: (state: never[], action: any, fullState: any) => never[]
        globalAnnotationsLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        globalAnnotations: never[]
        globalAnnotationsLoading: boolean
    }
    selectors: {
        globalAnnotations: (state: any, props: any) => never[]
        globalAnnotationsLoading: (state: any, props: any) => boolean
        activeGlobalAnnotations: (state: any, props: any) => any
    }
    values: {
        globalAnnotations: never[]
        globalAnnotationsLoading: boolean
        activeGlobalAnnotations: any
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        activeGlobalAnnotations: (arg1: any) => any
    }
}
