import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { FeatureType } from '~/types'

import type { featuresLogicType } from './featuresLogicType'

export const featuresLogic = kea<featuresLogicType>([
    path(['scenes', 'features', 'featuresLogic']),
    loaders({
        features: {
            __default: [] as FeatureType[],
            loadFeatureFlags: async () => {
                const response = await api.features.list()
                return response.results
            },
        },
    }),
    afterMount(async ({ actions }) => {
        await actions.loadFeatureFlags()
    }),
])
