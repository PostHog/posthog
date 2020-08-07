// Auto-generated with kea-typegen. DO NOT EDIT!

export interface funnelsModelType<SavedFunnel> {
    key: any
    actionCreators: {
        loadFunnels: () => {
            type: 'load funnels (models.funnelsModel)'
            payload: any
        }
        loadFunnelsSuccess: (
            funnels: SavedFunnel[]
        ) => {
            type: 'load funnels success (models.funnelsModel)'
            payload: {
                funnels: SavedFunnel[]
            }
        }
        loadFunnelsFailure: (
            error: string
        ) => {
            type: 'load funnels failure (models.funnelsModel)'
            payload: {
                error: string
            }
        }
        setNext: (
            next: any
        ) => {
            type: 'set next (models.funnelsModel)'
            payload: { next: any }
        }
        loadNext: () => {
            type: 'load next (models.funnelsModel)'
            payload: {
                value: boolean
            }
        }
        appendFunnels: (
            funnels: any
        ) => {
            type: 'append funnels (models.funnelsModel)'
            payload: { funnels: any }
        }
    }
    actionKeys: {
        'load funnels (models.funnelsModel)': 'loadFunnels'
        'load funnels success (models.funnelsModel)': 'loadFunnelsSuccess'
        'load funnels failure (models.funnelsModel)': 'loadFunnelsFailure'
        'set next (models.funnelsModel)': 'setNext'
        'load next (models.funnelsModel)': 'loadNext'
        'append funnels (models.funnelsModel)': 'appendFunnels'
    }
    actionTypes: {
        loadFunnels: 'load funnels (models.funnelsModel)'
        loadFunnelsSuccess: 'load funnels success (models.funnelsModel)'
        loadFunnelsFailure: 'load funnels failure (models.funnelsModel)'
        setNext: 'set next (models.funnelsModel)'
        loadNext: 'load next (models.funnelsModel)'
        appendFunnels: 'append funnels (models.funnelsModel)'
    }
    actions: {
        loadFunnels: () => void
        loadFunnelsSuccess: (funnels: SavedFunnel[]) => void
        loadFunnelsFailure: (error: string) => void
        setNext: (next: any) => void
        loadNext: () => void
        appendFunnels: (funnels: any) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['models', 'funnelsModel']
    pathString: 'models.funnelsModel'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        funnels: SavedFunnel[]
        funnelsLoading: boolean
        next: null | string
        loadingMore: boolean
    }
    reducerOptions: any
    reducers: {
        funnels: (state: SavedFunnel[], action: any, fullState: any) => SavedFunnel[]
        funnelsLoading: (state: boolean, action: any, fullState: any) => boolean
        next: (state: null | string, action: any, fullState: any) => null | string
        loadingMore: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        funnels: SavedFunnel[]
        funnelsLoading: boolean
        next: null | string
        loadingMore: boolean
    }
    selectors: {
        funnels: (state: any, props: any) => SavedFunnel[]
        funnelsLoading: (state: any, props: any) => boolean
        next: (state: any, props: any) => null | string
        loadingMore: (state: any, props: any) => boolean
    }
    values: {
        funnels: SavedFunnel[]
        funnelsLoading: boolean
        next: null | string
        loadingMore: boolean
    }
    _isKea: true
}
