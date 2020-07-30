// Auto-generated with kea-typegen. DO NOT EDIT!

export interface funnelsModelType {
    key: any
    actionCreators: {
        loadFunnels: () => {
            type: 'load funnels (frontend.src.models.funnelsModel)'
            payload: any
        }
        loadFunnelsSuccess: (
            funnels: any
        ) => {
            type: 'load funnels success (frontend.src.models.funnelsModel)'
            payload: {
                funnels: any
            }
        }
        loadFunnelsFailure: (
            error: string
        ) => {
            type: 'load funnels failure (frontend.src.models.funnelsModel)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'load funnels (frontend.src.models.funnelsModel)': 'loadFunnels'
        'load funnels success (frontend.src.models.funnelsModel)': 'loadFunnelsSuccess'
        'load funnels failure (frontend.src.models.funnelsModel)': 'loadFunnelsFailure'
    }
    actionTypes: {
        loadFunnels: 'load funnels (frontend.src.models.funnelsModel)'
        loadFunnelsSuccess: 'load funnels success (frontend.src.models.funnelsModel)'
        loadFunnelsFailure: 'load funnels failure (frontend.src.models.funnelsModel)'
    }
    actions: {
        loadFunnels: () => void
        loadFunnelsSuccess: (funnels: any) => void
        loadFunnelsFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'models', 'funnelsModel']
    pathString: 'frontend.src.models.funnelsModel'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        funnels: any
        funnelsLoading: boolean
    }
    reducerOptions: any
    reducers: {
        funnels: (state: any, action: any, fullState: any) => any
        funnelsLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        funnels: any
        funnelsLoading: boolean
    }
    selectors: {
        funnels: (state: any, props: any) => any
        funnelsLoading: (state: any, props: any) => boolean
    }
    values: {
        funnels: any
        funnelsLoading: boolean
    }
    _isKea: true
}
