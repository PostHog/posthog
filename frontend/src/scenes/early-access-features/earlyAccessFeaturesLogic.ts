import { afterMount, kea, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { Breadcrumb, EarlyAccessFeatureType } from '~/types'

import type { earlyAccessFeaturesLogicType } from './earlyAccessFeaturesLogicType'

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
