// Auto-generated with kea-typegen. DO NOT EDIT!

export interface annotationsModelType {
    key: any
    actionCreators: {
        createGlobalAnnotation: (
            content: any,
            date_marker: any,
            dashboard_item: any
        ) => {
            type: 'create global annotation (models.annotationsModel)'
            payload: { content: any; date_marker: any; created_at: Moment; dashboard_item: any }
        }
        deleteGlobalAnnotation: (
            id: any
        ) => {
            type: 'delete global annotation (models.annotationsModel)'
            payload: { id: any }
        }
        loadGlobalAnnotations: () => {
            type: 'load global annotations (models.annotationsModel)'
            payload: any
        }
        loadGlobalAnnotationsSuccess: (
            globalAnnotations: undefined[]
        ) => {
            type: 'load global annotations success (models.annotationsModel)'
            payload: {
                globalAnnotations: undefined[]
            }
        }
        loadGlobalAnnotationsFailure: (
            error: string
        ) => {
            type: 'load global annotations failure (models.annotationsModel)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'create global annotation (models.annotationsModel)': 'createGlobalAnnotation'
        'delete global annotation (models.annotationsModel)': 'deleteGlobalAnnotation'
        'load global annotations (models.annotationsModel)': 'loadGlobalAnnotations'
        'load global annotations success (models.annotationsModel)': 'loadGlobalAnnotationsSuccess'
        'load global annotations failure (models.annotationsModel)': 'loadGlobalAnnotationsFailure'
    }
    actionTypes: {
        createGlobalAnnotation: 'create global annotation (models.annotationsModel)'
        deleteGlobalAnnotation: 'delete global annotation (models.annotationsModel)'
        loadGlobalAnnotations: 'load global annotations (models.annotationsModel)'
        loadGlobalAnnotationsSuccess: 'load global annotations success (models.annotationsModel)'
        loadGlobalAnnotationsFailure: 'load global annotations failure (models.annotationsModel)'
    }
    actions: {
        createGlobalAnnotation: (
            content: any,
            date_marker: any,
            dashboard_item: any
        ) => {
            type: 'create global annotation (models.annotationsModel)'
            payload: { content: any; date_marker: any; created_at: Moment; dashboard_item: any }
        }
        deleteGlobalAnnotation: (
            id: any
        ) => {
            type: 'delete global annotation (models.annotationsModel)'
            payload: { id: any }
        }
        loadGlobalAnnotations: () => {
            type: 'load global annotations (models.annotationsModel)'
            payload: any
        }
        loadGlobalAnnotationsSuccess: (
            globalAnnotations: undefined[]
        ) => {
            type: 'load global annotations success (models.annotationsModel)'
            payload: {
                globalAnnotations: undefined[]
            }
        }
        loadGlobalAnnotationsFailure: (
            error: string
        ) => {
            type: 'load global annotations failure (models.annotationsModel)'
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
    path: ['models', 'annotationsModel']
    pathString: 'models.annotationsModel'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        globalAnnotations: undefined[]
        globalAnnotationsLoading: boolean
    }
    reducerOptions: any
    reducers: {
        globalAnnotations: (state: undefined[], action: any, fullState: any) => undefined[]
        globalAnnotationsLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        globalAnnotations: undefined[]
        globalAnnotationsLoading: boolean
    }
    selectors: {
        globalAnnotations: (state: any, props: any) => undefined[]
        globalAnnotationsLoading: (state: any, props: any) => boolean
        activeGlobalAnnotations: (state: any, props: any) => any
    }
    values: {
        globalAnnotations: undefined[]
        globalAnnotationsLoading: boolean
        activeGlobalAnnotations: any
    }
    _isKea: true
    __keaTypeGenInternalSelectorTypes: {
        activeGlobalAnnotations: (arg1: any) => any
    }
}
