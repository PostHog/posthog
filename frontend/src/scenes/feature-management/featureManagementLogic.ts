import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, urlToAction } from 'kea-router'
import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb, Feature } from '~/types'

import type { featureManagementLogicType } from './featureManagementLogicType'

export interface FeatureManagementLogicProps {
    id?: Feature['id']
}
export interface FeaturesResult {
    results: Feature[]
    count: number
    next?: string | null
    previous?: string | null
}

export const featureManagementLogic = kea<featureManagementLogicType>([
    props({} as FeatureManagementLogicProps),
    path(['scenes', 'features', 'featureManagementLogic']),
    connect({
        values: [teamLogic, ['currentTeamId']],
    }),
    actions({
        setActiveFeatureId: (activeFeatureId: Feature['id']) => ({ activeFeatureId }),
    }),
    reducers({
        activeFeatureId: [
            null as Feature['id'] | null,
            {
                setActiveFeatureId: (_, { activeFeatureId }) => activeFeatureId,
            },
        ],
    }),
    loaders(({ values }) => ({
        features: [
            null as null | FeaturesResult,
            {
                loadFeatures: async () => {
                    const response = await api.get(`api/projects/${values.currentTeamId}/features`)
                    return response as FeaturesResult
                },
            },
        ],
    })),
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
            if (id && String(values.activeFeatureId) !== id && id !== 'new') {
                actions.setActiveFeatureId(Number(id))
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadFeatures()
    }),
])
