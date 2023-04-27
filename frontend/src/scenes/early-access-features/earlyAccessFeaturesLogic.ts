import { afterMount, kea, path } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { EarlyAccsesFeatureType } from '~/types'

import type { earlyAccessFeaturesLogicType } from './earlyAccessFeaturesLogicType'

export const earlyAccessFeaturesLogic = kea<earlyAccessFeaturesLogicType>([
    path(['scenes', 'features', 'featuresLogic']),
    loaders({
        earlyAccessFeatures: {
            __default: [] as EarlyAccsesFeatureType[],
            loadEarlyAccessFeatures: async () => {
                const response = await api.earlyAccessFeatures.list()
                return response.results
            },
        },
    }),
    afterMount(async ({ actions }) => {
        await actions.loadEarlyAccessFeatures()
    }),
])
