import { kea } from 'kea'
import api from 'lib/api'
import { featureFlagsLogicType } from './featureFlagsLogicType'
import { FeatureFlagType } from '~/types'

export const featureFlagsLogic = kea<featureFlagsLogicType<FeatureFlagType>>({
    actions: {
        setFeatureFlag: (featureFlag: FeatureFlagType) => ({ featureFlag }),
        updateFeatureFlag: (id: number, payload: Partial<FeatureFlagType>) => ({ id, payload }),
    },
    loaders: {
        featureFlags: {
            __default: [] as FeatureFlagType[],
            loadFeatureFlags: async () => {
                const response = await api.get('api/feature_flag/')
                return response.results as FeatureFlagType[]
            },
        },
    },
    listeners: ({ actions }) => ({
        updateFeatureFlag: async ({ id, payload }) => {
            const response = await api.update(`api/feature_flag/${id}`, payload)
            actions.setFeatureFlag(response)
        },
    }),
    reducers: () => ({
        featureFlags: {
            setFeatureFlag: (state, { featureFlag }) =>
                [...state].map((flag) => (flag.id === featureFlag.id ? featureFlag : flag)),
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadFeatureFlags()
        },
    }),
})
