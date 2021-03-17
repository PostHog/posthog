import { kea } from 'kea'
import api from 'lib/api'
import { featureFlagsLogicType } from './featureFlagsLogicType'
import { FeatureFlagType } from '~/types'
import { router } from 'kea-router'

export const featureFlagsLogic = kea<featureFlagsLogicType<FeatureFlagType>>({
    actions: () => ({
        updateFeatureFlag: (featureFlag: FeatureFlagType) => ({ featureFlag }),
        setOpenedFeatureFlag: (featureFlagId: number | 'new' | null) => ({ featureFlagId }),
    }),
    reducers: () => ({
        openedFeatureFlagId: [
            null as number | 'new' | null,
            {
                setOpenedFeatureFlag: (_, { featureFlagId }) => featureFlagId,
            },
        ],
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
    urlToAction: ({ actions }) => ({
        '/feature_flags/*': ({ _: id }: { _: number | 'new' | null | undefined }) => {
            if (id) {
                actions.setOpenedFeatureFlag(id)
            }
        },
    }),
    actionToUrl: ({ values }) => ({
        setOpenedFeatureFlag: () => {
            const routeId = values.openedFeatureFlagId ? `/${values.openedFeatureFlagId}` : ''
            return [`/feature_flags${routeId}`, router.values.searchParams, router.values.hashParams]
        },
    }),
})
