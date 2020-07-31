// Auto-generated with kea-typegen. DO NOT EDIT!

export interface funnelVizLogicType {
    key: unknown
    actionCreators: {
        loadResults: (
            refresh?: any
        ) => {
            type: 'load results (scenes.funnels.funnelVizLogic)'
            payload: any
        }
        loadResultsSuccess: (
            results: any
        ) => {
            type: 'load results success (scenes.funnels.funnelVizLogic)'
            payload: {
                results: any
            }
        }
        loadResultsFailure: (
            error: string
        ) => {
            type: 'load results failure (scenes.funnels.funnelVizLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'load results (scenes.funnels.funnelVizLogic)': 'loadResults'
        'load results success (scenes.funnels.funnelVizLogic)': 'loadResultsSuccess'
        'load results failure (scenes.funnels.funnelVizLogic)': 'loadResultsFailure'
    }
    actionTypes: {
        loadResults: 'load results (scenes.funnels.funnelVizLogic)'
        loadResultsSuccess: 'load results success (scenes.funnels.funnelVizLogic)'
        loadResultsFailure: 'load results failure (scenes.funnels.funnelVizLogic)'
    }
    actions: {
        loadResults: (refresh?: any) => void
        loadResultsSuccess: (results: any) => void
        loadResultsFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: {
        results: any
        resultsLoading: boolean
    }
    events: any
    path: ['scenes', 'funnels', 'funnelVizLogic']
    pathString: 'scenes.funnels.funnelVizLogic'
    props: Record<string, unknown>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        results: any
        resultsLoading: boolean
    }
    reducerOptions: any
    reducers: {
        results: (state: any, action: any, fullState: any) => any
        resultsLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        results: any
        resultsLoading: boolean
    }
    selectors: {
        results: (state: any, props: any) => any
        resultsLoading: (state: any, props: any) => boolean
    }
    values: {
        results: any
        resultsLoading: boolean
    }
    _isKea: true
}
