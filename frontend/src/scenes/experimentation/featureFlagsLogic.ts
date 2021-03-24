import { kea } from 'kea'
import api from 'lib/api'
import { featureFlagsLogicType } from './featureFlagsLogicType'
import { FeatureFlagType } from '~/types'

export const featureFlagsLogic = kea<featureFlagsLogicType<FeatureFlagType>>({
    loaders: ({ values }) => ({
        featureFlags: {
            __default: [] as FeatureFlagType[],
            loadFeatureFlags: async () => {
                const response = await api.get('api/feature_flag/')
                return response.results as FeatureFlagType[]
            },
            updateFeatureFlag: async ({ id, payload }: { id: string; payload: Partial<FeatureFlagType> }) => {
                const response = await api.update(`api/feature_flag/${id}`, payload)
                return [...values.featureFlags].map((flag) => (flag.id === response.id ? response : flag))
            },
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadFeatureFlags()
        },
    }),
})
