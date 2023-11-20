import { afterMount, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Breadcrumb, EarlyAccessFeatureType } from '~/types'

import type { earlyAccessFeaturesLogicType } from './earlyAccessFeaturesLogicType'
import { urls } from 'scenes/urls'
import { Scene } from 'scenes/sceneTypes'

export const earlyAccessFeaturesLogic = kea<earlyAccessFeaturesLogicType>([
    path(['scenes', 'features', 'featuresLogic']),
    loaders({
        earlyAccessFeatures: {
            __default: [] as EarlyAccessFeatureType[],
            loadEarlyAccessFeatures: async () => {
                const response = await api.earlyAccessFeatures.list()
                return response.results
            },
        },
    }),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    key: Scene.EarlyAccessFeatures,
                    name: 'Early access features',
                    path: urls.earlyAccessFeatures(),
                },
            ],
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadEarlyAccessFeatures()
    }),
])
