// Auto-generated with kea-typegen. DO NOT EDIT!

export interface funnelVizLogicType {
    key: any
    actionCreators: {
        loadResults: () => {
            type: 'load results (scenes.funnels.funnelVizLogic)'
            payload: any
        }
        loadResultsSuccess: (
            results: never[]
        ) => {
            type: 'load results success (scenes.funnels.funnelVizLogic)'
            payload: {
                results: never[]
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
        loadResults: () => void
        loadResultsSuccess: (results: never[]) => void
        loadResultsFailure: (error: string) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['scenes', 'funnels', 'funnelVizLogic']
    pathString: 'scenes.funnels.funnelVizLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        results: never[]
        resultsLoading: boolean
    }
    reducerOptions: any
    reducers: {
        results: (state: never[], action: any, fullState: any) => never[]
        resultsLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        results: never[]
        resultsLoading: boolean
    }
    selectors: {
        results: (state: any, props: any) => never[]
        resultsLoading: (state: any, props: any) => boolean
    }
    values: {
        results: never[]
        resultsLoading: boolean
    }
    _isKea: true
}
