import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { objectsEqual } from 'lib/utils'
import { deleteWithUndo } from 'lib/utils/deleteWithUndo'
import { Scene } from 'scenes/sceneTypes'
import { sceneConfigurations } from 'scenes/scenes'
import { urls } from 'scenes/urls'

import { Breadcrumb, HeatmapFilters, HeatmapScreenshotType } from '~/types'

import type { heatmapsSceneLogicType } from './heatmapsSceneLogicType'

export const DEFAULT_HEATMAP_FILTERS = {
    createdBy: 'All users',
    search: '',
    page: 1,
}

export const heatmapsSceneLogic = kea<heatmapsSceneLogicType>([
    path(['scenes', 'heatmaps', 'heatmapsSceneLogic']),
    actions({
        loadSavedHeatmaps: true,
        setSavedHeatmaps: (items: HeatmapScreenshotType[]) => ({ items }),
        setLoading: (loading: boolean) => ({ loading }),
        deleteHeatmap: (short_id: string) => ({ short_id }),
        setHeatmapsFilters: (filters: HeatmapFilters) => ({ filters }),
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
        filters: [
            DEFAULT_HEATMAP_FILTERS,
            { persist: true },
            {
                setHeatmapsFilters: (_, { filters }) => filters,
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
    listeners(({ actions, values }) => ({
        loadSavedHeatmaps: async (_, breakpoint) => {
            if (!objectsEqual(values.filters, DEFAULT_HEATMAP_FILTERS)) {
                await breakpoint(300)
            }
            actions.setLoading(true)
            try {
                const f = values.filters || {}
                const createdBy = f.createdBy === 'All users' ? undefined : f.createdBy
                const params: Record<string, any> = {
                    limit: 100,
                    search: f.search || undefined,
                    created_by: createdBy || undefined,
                    order: f.order || '-created_at',
                }
                const response = await api.heatmapSaved.list(params)
                actions.setSavedHeatmaps(response.results || [])
            } finally {
                actions.setLoading(false)
            }
        },
        deleteHeatmap: async ({ short_id }) => {
            const item = values.savedHeatmaps.find((h) => h.short_id === short_id)
            const object = { id: item?.id, short_id, name: item?.name || item?.url || 'Heatmap' }
            await deleteWithUndo({
                object,
                idField: 'short_id',
                // project/environment-scoped API path; backend must support soft-delete via PATCH
                endpoint: 'environments/@current/saved',
                callback: () => actions.loadSavedHeatmaps(),
            })
        },
        setHeatmapsFilters: () => {
            actions.loadSavedHeatmaps()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSavedHeatmaps()
    }),
])
