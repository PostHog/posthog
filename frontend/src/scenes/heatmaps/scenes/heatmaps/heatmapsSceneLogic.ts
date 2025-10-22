import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { Breadcrumb, HeatmapScreenshotType } from '~/types'

import type { heatmapsSceneLogicType } from './heatmapsSceneLogicType'

export const heatmapsSceneLogic = kea<heatmapsSceneLogicType>([
    path(['scenes', 'heatmaps', 'heatmapsSceneLogic']),
    actions({
        loadSavedHeatmaps: true,
        setSavedHeatmaps: (items: HeatmapScreenshotType[]) => ({ items }),
        setLoading: (loading: boolean) => ({ loading }),
        deleteHeatmap: (short_id: string) => ({ short_id }),
    }),
    reducers({
        savedHeatmaps: [
            [] as HeatmapScreenshotType[],
            {
                setSavedHeatmaps: (_, { items }) => items,
            },
        ],
        savedHeatmapsLoading: [
            false,
            {
                setLoading: (_, { loading }) => loading,
            },
        ],
    }),
    selectors(() => ({
        breadcrumbs: [
            () => [],
            (): Breadcrumb[] => {
                return [
                    {
                        key: Scene.Heatmaps,
                        name: sceneConfigurations[Scene.Heatmaps].name || 'Heatmaps',
                        path: urls.heatmaps(),
                        iconType: sceneConfigurations[Scene.Heatmaps].iconType || 'default_icon_type',
                    },
                ]
            },
        ],
    })),
    listeners(({ actions }) => ({
        loadSavedHeatmaps: async () => {
            actions.setLoading(true)
            try {
                const response = await api.heatmapSaved.list({ limit: 100 })
                actions.setSavedHeatmaps(response.results || [])
            } finally {
                actions.setLoading(false)
            }
        },
        deleteHeatmap: async ({ short_id }) => {
            try {
                await api.heatmapSaved.delete(short_id)
                actions.loadSavedHeatmaps()
            } catch (error) {
                console.error(error)
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSavedHeatmaps()
    }),
])
