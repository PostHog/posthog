import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'

import { lemonToast } from '@posthog/lemon-ui'

import { teamLogic } from 'scenes/teamLogic'

import { Breadcrumb } from '~/types'

import {
    catalogDimensionsPartialUpdate,
    catalogEntitiesBrowserRetrieve,
    catalogEntitiesClusterCreate,
    catalogEntitiesDeriveCreate,
    catalogEntitiesPartialUpdate,
    catalogMetricsPartialUpdate,
} from 'products/catalog/frontend/generated/api'
import type {
    CatalogBrowserDTOApi,
    CatalogDimensionDTOApi,
    CatalogEntityDTOApi,
    CatalogMetricDTOApi,
    PatchedUpdateDimensionInputApi,
    PatchedUpdateEntityInputApi,
    PatchedUpdateMetricInputApi,
} from 'products/catalog/frontend/generated/api.schemas'

import type { catalogBrowserSceneLogicType } from './catalogBrowserSceneLogicType'

export type CatalogReviewStatus = 'proposed' | 'accepted' | 'rejected' | 'stale'

export const catalogBrowserSceneLogic = kea<catalogBrowserSceneLogicType>([
    path(['products', 'catalog', 'frontend', 'catalogBrowserSceneLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId']],
    })),

    actions({
        setSelectedEntityId: (entityId: string | null) => ({ entityId }),
        deriveCatalog: true,
        clusterCatalog: true,
        updateEntity: (entityId: string, edits: PatchedUpdateEntityInputApi) => ({ entityId, edits }),
        updateMetric: (metricId: string, edits: PatchedUpdateMetricInputApi) => ({ metricId, edits }),
        updateDimension: (dimensionId: string, edits: PatchedUpdateDimensionInputApi) => ({ dimensionId, edits }),
        // Local cache updates so accept/reject feels instant (no full reload).
        replaceEntity: (entity: CatalogEntityDTOApi) => ({ entity }),
        replaceMetric: (metric: CatalogMetricDTOApi) => ({ metric }),
        replaceDimension: (dimension: CatalogDimensionDTOApi) => ({ dimension }),
    }),

    loaders(({ values }) => ({
        browser: [
            null as CatalogBrowserDTOApi | null,
            {
                loadBrowser: async () => {
                    return await catalogEntitiesBrowserRetrieve(String(values.currentProjectId))
                },
            },
        ],
    })),

    reducers({
        selectedEntityId: [
            null as string | null,
            {
                setSelectedEntityId: (_, { entityId }) => entityId,
            },
        ],
        browser: {
            replaceEntity: (state, { entity }) => {
                if (!state) {
                    return state
                }
                return {
                    ...state,
                    entities: state.entities.map((e) => (e.id === entity.id ? entity : e)),
                }
            },
            replaceMetric: (state, { metric }) => {
                if (!state) {
                    return state
                }
                return {
                    ...state,
                    metrics: state.metrics.map((m) => (m.id === metric.id ? metric : m)),
                }
            },
            replaceDimension: (state, { dimension }) => {
                if (!state) {
                    return state
                }
                return {
                    ...state,
                    dimensions: state.dimensions.map((d) => (d.id === dimension.id ? dimension : d)),
                }
            },
        },
    }),

    selectors({
        entities: [(s) => [s.browser], (browser): CatalogEntityDTOApi[] => browser?.entities ?? []],
        metrics: [(s) => [s.browser], (browser): CatalogMetricDTOApi[] => browser?.metrics ?? []],
        dimensions: [(s) => [s.browser], (browser): CatalogDimensionDTOApi[] => browser?.dimensions ?? []],
        selectedEntity: [
            (s) => [s.entities, s.selectedEntityId],
            (entities, id): CatalogEntityDTOApi | null => entities.find((e) => e.id === id) ?? null,
        ],
        metricsForSelectedEntity: [
            (s) => [s.metrics, s.selectedEntityId],
            (metrics, entityId): CatalogMetricDTOApi[] =>
                entityId ? metrics.filter((m) => m.entity_id === entityId) : [],
        ],
        dimensionsForSelectedEntity: [
            (s) => [s.dimensions, s.selectedEntityId],
            (dimensions, entityId): CatalogDimensionDTOApi[] =>
                entityId ? dimensions.filter((d) => d.entity_id === entityId) : [],
        ],
        breadcrumbs: [() => [], (): Breadcrumb[] => [{ key: 'catalog', name: 'Catalog' }]],
    }),

    listeners(({ values, actions }) => ({
        deriveCatalog: async () => {
            try {
                const result = await catalogEntitiesDeriveCreate(String(values.currentProjectId))
                const total = result.entities_created + result.metrics_created + result.dimensions_created
                if (total === 0) {
                    lemonToast.info('No new proposals — catalog is already up to date.')
                } else {
                    lemonToast.success(
                        `Proposed ${result.entities_created} entities, ${result.metrics_created} metrics, ${result.dimensions_created} dimensions.`
                    )
                }
                actions.loadBrowser()
            } catch (error) {
                lemonToast.error(`Failed to derive catalog: ${(error as Error).message}`)
            }
        },
        clusterCatalog: async () => {
            try {
                await catalogEntitiesClusterCreate(String(values.currentProjectId))
                lemonToast.info(
                    'Clustering agent started. Entities will update with merge proposals as the agent works — refresh the page in a few minutes to see them.'
                )
            } catch (error) {
                lemonToast.error(`Failed to start clustering: ${(error as Error).message}`)
            }
        },
        updateEntity: async ({ entityId, edits }) => {
            try {
                const updated = await catalogEntitiesPartialUpdate(String(values.currentProjectId), entityId, edits)
                actions.replaceEntity(updated)
            } catch (error) {
                lemonToast.error(`Failed to update entity: ${(error as Error).message}`)
            }
        },
        updateMetric: async ({ metricId, edits }) => {
            try {
                const updated = await catalogMetricsPartialUpdate(String(values.currentProjectId), metricId, edits)
                actions.replaceMetric(updated)
            } catch (error) {
                lemonToast.error(`Failed to update metric: ${(error as Error).message}`)
            }
        },
        updateDimension: async ({ dimensionId, edits }) => {
            try {
                const updated = await catalogDimensionsPartialUpdate(
                    String(values.currentProjectId),
                    dimensionId,
                    edits
                )
                actions.replaceDimension(updated)
            } catch (error) {
                lemonToast.error(`Failed to update dimension: ${(error as Error).message}`)
            }
        },
    })),

    urlToAction(({ actions }) => ({
        '/catalog': () => {
            actions.loadBrowser()
        },
    })),
])
