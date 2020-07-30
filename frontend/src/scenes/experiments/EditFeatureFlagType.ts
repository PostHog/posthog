// Auto-generated with kea-typegen. DO NOT EDIT!

export interface editLogicType {
    key: any
    actionCreators: {
        setRolloutPercentage: (
            rollout_percentage: any
        ) => {
            type: 'set rollout percentage (frontend.src.scenes.experiments.EditFeatureFlag)'
            payload: { rollout_percentage: any }
        }
        setFilters: (
            filters: any
        ) => {
            type: 'set filters (frontend.src.scenes.experiments.EditFeatureFlag)'
            payload: { filters: any }
        }
    }
    actionKeys: {
        'set rollout percentage (frontend.src.scenes.experiments.EditFeatureFlag)': 'setRolloutPercentage'
        'set filters (frontend.src.scenes.experiments.EditFeatureFlag)': 'setFilters'
    }
    actionTypes: {
        setRolloutPercentage: 'set rollout percentage (frontend.src.scenes.experiments.EditFeatureFlag)'
        setFilters: 'set filters (frontend.src.scenes.experiments.EditFeatureFlag)'
    }
    actions: {
        setRolloutPercentage: (rollout_percentage: any) => void
        setFilters: (filters: any) => void
    }
    cache: Record<string, any>
    connections: any
    constants: any
    defaults: any
    events: any
    path: ['frontend', 'src', 'scenes', 'experiments', 'EditFeatureFlag']
    pathString: 'frontend.src.scenes.experiments.EditFeatureFlag'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        filters: any
        rollout_percentage: any
    }
    reducerOptions: any
    reducers: {
        filters: (state: any, action: any, fullState: any) => any
        rollout_percentage: (state: any, action: any, fullState: any) => any
    }
    selector: (
        state: any
    ) => {
        filters: any
        rollout_percentage: any
    }
    selectors: {
        filters: (state: any, props: any) => any
        rollout_percentage: (state: any, props: any) => any
    }
    values: {
        filters: any
        rollout_percentage: any
    }
    _isKea: true
}
