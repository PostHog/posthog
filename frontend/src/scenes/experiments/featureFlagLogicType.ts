// Auto-generated with kea-typegen. DO NOT EDIT!

export interface featureFlagLogicType {
    key: any
    actionCreators: {
        setFunnel: (
            funnel: any,
            update: any
        ) => {
            type: 'set funnel (scenes.experiments.featureFlagLogic)'
            payload: { funnel: any; update: any }
        }
        loadFeatureFlags: () => {
            type: 'load feature flags (scenes.experiments.featureFlagLogic)'
            payload: any
        }
        loadFeatureFlagsSuccess: (
            featureFlags: undefined[]
        ) => {
            type: 'load feature flags success (scenes.experiments.featureFlagLogic)'
            payload: {
                featureFlags: undefined[]
            }
        }
        loadFeatureFlagsFailure: (
            error: string
        ) => {
            type: 'load feature flags failure (scenes.experiments.featureFlagLogic)'
            payload: {
                error: string
            }
        }
        updateFeatureFlag: (
            featureFlag: any
        ) => {
            type: 'update feature flag (scenes.experiments.featureFlagLogic)'
            payload: any
        }
        updateFeatureFlagSuccess: (
            featureFlags: undefined[]
        ) => {
            type: 'update feature flag success (scenes.experiments.featureFlagLogic)'
            payload: {
                featureFlags: undefined[]
            }
        }
        updateFeatureFlagFailure: (
            error: string
        ) => {
            type: 'update feature flag failure (scenes.experiments.featureFlagLogic)'
            payload: {
                error: string
            }
        }
        createFeatureFlag: (
            featureFlag: any
        ) => {
            type: 'create feature flag (scenes.experiments.featureFlagLogic)'
            payload: any
        }
        createFeatureFlagSuccess: (
            featureFlags: undefined[]
        ) => {
            type: 'create feature flag success (scenes.experiments.featureFlagLogic)'
            payload: {
                featureFlags: undefined[]
            }
        }
        createFeatureFlagFailure: (
            error: string
        ) => {
            type: 'create feature flag failure (scenes.experiments.featureFlagLogic)'
            payload: {
                error: string
            }
        }
    }
    actionKeys: {
        'set funnel (scenes.experiments.featureFlagLogic)': 'setFunnel'
        'load feature flags (scenes.experiments.featureFlagLogic)': 'loadFeatureFlags'
        'load feature flags success (scenes.experiments.featureFlagLogic)': 'loadFeatureFlagsSuccess'
        'load feature flags failure (scenes.experiments.featureFlagLogic)': 'loadFeatureFlagsFailure'
        'update feature flag (scenes.experiments.featureFlagLogic)': 'updateFeatureFlag'
        'update feature flag success (scenes.experiments.featureFlagLogic)': 'updateFeatureFlagSuccess'
        'update feature flag failure (scenes.experiments.featureFlagLogic)': 'updateFeatureFlagFailure'
        'create feature flag (scenes.experiments.featureFlagLogic)': 'createFeatureFlag'
        'create feature flag success (scenes.experiments.featureFlagLogic)': 'createFeatureFlagSuccess'
        'create feature flag failure (scenes.experiments.featureFlagLogic)': 'createFeatureFlagFailure'
    }
    actionTypes: {
        setFunnel: 'set funnel (scenes.experiments.featureFlagLogic)'
        loadFeatureFlags: 'load feature flags (scenes.experiments.featureFlagLogic)'
        loadFeatureFlagsSuccess: 'load feature flags success (scenes.experiments.featureFlagLogic)'
        loadFeatureFlagsFailure: 'load feature flags failure (scenes.experiments.featureFlagLogic)'
        updateFeatureFlag: 'update feature flag (scenes.experiments.featureFlagLogic)'
        updateFeatureFlagSuccess: 'update feature flag success (scenes.experiments.featureFlagLogic)'
        updateFeatureFlagFailure: 'update feature flag failure (scenes.experiments.featureFlagLogic)'
        createFeatureFlag: 'create feature flag (scenes.experiments.featureFlagLogic)'
        createFeatureFlagSuccess: 'create feature flag success (scenes.experiments.featureFlagLogic)'
        createFeatureFlagFailure: 'create feature flag failure (scenes.experiments.featureFlagLogic)'
    }
    actions: {
        setFunnel: (
            funnel: any,
            update: any
        ) => {
            type: 'set funnel (scenes.experiments.featureFlagLogic)'
            payload: { funnel: any; update: any }
        }
        loadFeatureFlags: () => {
            type: 'load feature flags (scenes.experiments.featureFlagLogic)'
            payload: any
        }
        loadFeatureFlagsSuccess: (
            featureFlags: undefined[]
        ) => {
            type: 'load feature flags success (scenes.experiments.featureFlagLogic)'
            payload: {
                featureFlags: undefined[]
            }
        }
        loadFeatureFlagsFailure: (
            error: string
        ) => {
            type: 'load feature flags failure (scenes.experiments.featureFlagLogic)'
            payload: {
                error: string
            }
        }
        updateFeatureFlag: (
            featureFlag: any
        ) => {
            type: 'update feature flag (scenes.experiments.featureFlagLogic)'
            payload: any
        }
        updateFeatureFlagSuccess: (
            featureFlags: undefined[]
        ) => {
            type: 'update feature flag success (scenes.experiments.featureFlagLogic)'
            payload: {
                featureFlags: undefined[]
            }
        }
        updateFeatureFlagFailure: (
            error: string
        ) => {
            type: 'update feature flag failure (scenes.experiments.featureFlagLogic)'
            payload: {
                error: string
            }
        }
        createFeatureFlag: (
            featureFlag: any
        ) => {
            type: 'create feature flag (scenes.experiments.featureFlagLogic)'
            payload: any
        }
        createFeatureFlagSuccess: (
            featureFlags: undefined[]
        ) => {
            type: 'create feature flag success (scenes.experiments.featureFlagLogic)'
            payload: {
                featureFlags: undefined[]
            }
        }
        createFeatureFlagFailure: (
            error: string
        ) => {
            type: 'create feature flag failure (scenes.experiments.featureFlagLogic)'
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
    path: ['scenes', 'experiments', 'featureFlagLogic']
    pathString: 'scenes.experiments.featureFlagLogic'
    propTypes: any
    props: Record<string, any>
    reducer: (
        state: any,
        action: () => any,
        fullState: any
    ) => {
        featureFlags: undefined[]
        featureFlagsLoading: boolean
    }
    reducerOptions: any
    reducers: {
        featureFlags: (state: undefined[], action: any, fullState: any) => undefined[]
        featureFlagsLoading: (state: boolean, action: any, fullState: any) => boolean
    }
    selector: (
        state: any
    ) => {
        featureFlags: undefined[]
        featureFlagsLoading: boolean
    }
    selectors: {
        featureFlags: (state: any, props: any) => undefined[]
        featureFlagsLoading: (state: any, props: any) => boolean
    }
    values: {
        featureFlags: undefined[]
        featureFlagsLoading: boolean
    }
    _isKea: true
}
