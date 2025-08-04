import { actions, afterMount, beforeUnmount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'
import api, { ApiMethodOptions, PaginatedResponse } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import posthog from 'posthog-js'

import { ExternalDataSchemaStatus, ExternalDataSource } from '~/types'

import type { externalDataSourcesLogicType } from './externalDataSourcesLogicType'

const REFRESH_INTERVAL = 10000

export const externalDataSourcesLogic = kea<externalDataSourcesLogicType>([
    path(['scenes', 'data-warehouse', 'externalDataSourcesLogic']),
    actions({
        abortAnyRunningQuery: true,
        deleteSource: (source: ExternalDataSource) => ({ source }),
        reloadSource: (source: ExternalDataSource) => ({ source }),
        reloadSourceSuccess: (source: ExternalDataSource) => ({ source }),
        reloadSourceFailure: (source: ExternalDataSource, error: Error) => ({ source, error }),
    }),
    loaders(({ cache, actions, values }) => ({
        dataWarehouseSources: [
            null as PaginatedResponse<ExternalDataSource> | null,
            {
                loadSources: async (_, breakpoint) => {
                    actions.abortAnyRunningQuery()

                    cache.abortController = new AbortController()
                    const methodOptions: ApiMethodOptions = {
                        signal: cache.abortController.signal,
                    }

                    const res = await api.externalDataSources.list(methodOptions)
                    breakpoint()

                    cache.abortController = null
                    return res
                },
                updateSource: async (source: ExternalDataSource) => {
                    const updatedSource = await api.externalDataSources.update(source.id, source)
                    const currentSources = values.dataWarehouseSources
                    if (!currentSources) {
                        return currentSources
                    }

                    return {
                        ...currentSources,
                        results: currentSources.results.map((s) => (s.id === updatedSource.id ? updatedSource : s)),
                    }
                },
            },
        ],
    })),
    reducers(({ cache }) => ({
        dataWarehouseSourcesLoading: [
            false,
            {
                loadSources: () => true,
                loadSourcesFailure: () => cache.abortController !== null,
                loadSourcesSuccess: () => cache.abortController !== null,
            },
        ],
    })),
    listeners(({ cache, actions, values }) => ({
        abortAnyRunningQuery: () => {
            if (cache.abortController) {
                cache.abortController.abort()
                cache.abortController = null
            }
        },
        deleteSource: async ({ source }) => {
            try {
                await api.externalDataSources.delete(source.id)
                actions.loadSources(null)
                posthog.capture('source deleted', { sourceType: source.source_type })
            } catch (error) {
                lemonToast.error('Failed to delete source')
                posthog.captureException(new Error('Failed to delete source', { cause: error }))
            }
        },
        reloadSource: async ({ source }) => {
            // Optimistic UI updates
            const clonedSources = JSON.parse(
                JSON.stringify(values.dataWarehouseSources?.results ?? [])
            ) as ExternalDataSource[]
            const sourceIndex = clonedSources.findIndex((n) => n.id === source.id)
            if (sourceIndex >= 0) {
                clonedSources[sourceIndex].status = 'Running'
                clonedSources[sourceIndex].schemas = clonedSources[sourceIndex].schemas.map((n) => {
                    if (n.should_sync) {
                        return { ...n, status: ExternalDataSchemaStatus.Running }
                    }
                    return n
                })

                actions.loadSourcesSuccess({
                    ...values.dataWarehouseSources,
                    results: clonedSources,
                })
            }

            try {
                await api.externalDataSources.reload(source.id)
                actions.loadSources(null)
                actions.reloadSourceSuccess(source)
                posthog.capture('source reloaded', { sourceType: source.source_type })
            } catch (error) {
                lemonToast.error('Failed to reload source')
                posthog.captureException(new Error('Failed to reload source', { cause: error }))
                actions.reloadSourceFailure(
                    source,
                    error instanceof Error ? error : new Error('Failed to reload source')
                )
            }
        },
        loadSourcesSuccess: () => {
            clearTimeout(cache.refreshTimeout)
            if (router.values.location.pathname.includes('data-warehouse')) {
                cache.refreshTimeout = setTimeout(() => {
                    actions.loadSources(null)
                }, REFRESH_INTERVAL)
            }
        },
        loadSourcesFailure: () => {
            clearTimeout(cache.refreshTimeout)
            if (router.values.location.pathname.includes('data-warehouse')) {
                cache.refreshTimeout = setTimeout(() => {
                    actions.loadSources(null)
                }, REFRESH_INTERVAL)
            }
        },
    })),
    urlToAction(({ actions }) => ({
        '/data-warehouse/*': () => {
            actions.loadSources(null)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSources(null)
    }),
    beforeUnmount(({ cache }) => {
        if (cache.abortController) {
            cache.abortController.abort()
            cache.abortController = null
        }
        clearTimeout(cache.refreshTimeout)
    }),
])
