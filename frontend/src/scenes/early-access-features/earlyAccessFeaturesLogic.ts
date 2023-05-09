import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { Breadcrumb, EarlyAccsesFeatureType } from '~/types'

import type { earlyAccessFeaturesLogicType } from './earlyAccessFeaturesLogicType'
import { urls } from 'scenes/urls'

export const earlyAccessFeaturesLogic = kea<earlyAccessFeaturesLogicType>([
    path(['scenes', 'features', 'featuresLogic']),
    actions({
        deleteEarlyAccessFeatureById: (id: string) => ({ id }),
    }),
    loaders({
        earlyAccessFeatures: {
            __default: [] as EarlyAccsesFeatureType[],
            loadEarlyAccessFeatures: async () => {
                const response = await api.earlyAccessFeatures.list()
                return response.results
            },
        },
    }),
    reducers({
        earlyAccessFeatures: {
            deleteEarlyAccessFeatureById: (state, { id }) =>
                state.filter((earlyAccessFeature) => earlyAccessFeature.id !== id),
        },
    }),
    selectors({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => [
                {
                    name: 'Early Access Features',
                    path: urls.earlyAccessFeatures(),
                },
            ],
        ],
    }),
    afterMount(async ({ actions }) => {
        await actions.loadEarlyAccessFeatures()
    }),
])
