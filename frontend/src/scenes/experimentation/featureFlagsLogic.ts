import { kea } from 'kea'
import api from 'lib/api'
import { featureFlagsLogicType } from './featureFlagsLogicType'
import { FeatureFlagType } from '~/types'

export const featureFlagsLogic = kea<featureFlagsLogicType<FeatureFlagType>>({
    actions: () => ({
        updateFeatureFlag: (featureFlag: FeatureFlagType) => ({ featureFlag }),
    }),
    loaders: {
        featureFlags: {
            __default: [] as FeatureFlagType[],
            loadFeatureFlags: async () => {
                const response = await api.get('api/feature_flag/')
                return response.results as FeatureFlagType[]
            },
        },
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadFeatureFlags()
        },
    }),
})
