import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import api, { CountedPaginatedResponse } from 'lib/api'
import { projectLogic } from 'scenes/projectLogic'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb, FeatureType } from '~/types'

import type { featureManagementLogicType } from './featureManagementLogicType'

export interface FeatureManagementLogicProps {
    id?: FeatureType['id']
}

export type FeaturesResult = CountedPaginatedResponse<FeatureType>

export const featureManagementLogic = kea<featureManagementLogicType>([
    props({} as FeatureManagementLogicProps),
    path(['scenes', 'features', 'featureManagementLogic']),
    connect({
        values: [teamLogic, ['currentTeamId'], projectLogic, ['currentProjectId']],
    }),
    actions({
        setActiveFeatureId: (activeFeatureId: FeatureType['id']) => ({ activeFeatureId }),
    }),
    reducers({
        activeFeatureId: [
            null as FeatureType['id'] | null,
            {
                setActiveFeatureId: (_, { activeFeatureId }) => activeFeatureId,
            },
        ],
    }),
    loaders({
        features: [
            { results: [], count: 0, offset: 0 } as FeaturesResult,
            {
                loadFeatures: () => api.features.list(),
            },
        ],
    }),
    selectors({
        activeFeature: [
            (s) => [s.activeFeatureId, s.features],
            (activeFeatureId, features) => features?.results.find((feature) => feature.id === activeFeatureId) || null,
        ],
        breadcrumbs: [
            (s) => [s.activeFeatureId, s.activeFeature],
            (activeFeatureId, activeFeature): Breadcrumb[] => {
                const breadcrumbs: Breadcrumb[] = [
                    {
                        key: Scene.FeatureManagement,
                        name: 'Features',
                        path: urls.featureManagement(),
                    },
                ]

                if (activeFeatureId) {
                    breadcrumbs.push({
                        key: [Scene.FeatureManagement, activeFeatureId],
                        name: activeFeature?.name ?? 'Feature',
                        path: urls.featureManagement(String(activeFeatureId)),
                    })
                }

                return breadcrumbs
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        loadFeaturesSuccess: ({ features }) => {
            console.log('loadFeaturesSuccess', { features, active: values.activeFeatureId })
            if (values.activeFeatureId === null && features.results.length > 0) {
                actions.setActiveFeatureId(features.results[0].id)
            }
        },
    })),
    actionToUrl({
        setActiveFeatureId: ({ activeFeatureId }) => {
            return urls.featureManagement(activeFeatureId)
        },
    }),
    urlToAction(({ actions, values }) => ({
        '/features/:id': ({ id }) => {
            console.log('urlToAction', { id })

            if (id && String(values.activeFeatureId) !== id) {
                actions.setActiveFeatureId(id)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadFeatures()
    }),
])
