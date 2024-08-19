import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import posthog from 'posthog-js'

import { ExternalDataJob, ExternalDataSourceSchema, ExternalDataStripeSource } from '~/types'

import type { dataWarehouseSourceSettingsLogicType } from './dataWarehouseSourceSettingsLogicType'

export interface DataWarehouseSourceSettingsLogicProps {
    id: string
}

const REFRESH_INTERVAL = 5000

export const dataWarehouseSourceSettingsLogic = kea<dataWarehouseSourceSettingsLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'source', 'dataWarehouseSourceSettingsLogic']),
    props({} as DataWarehouseSourceSettingsLogicProps),
    key(({ id }) => id),
    actions({
        setSourceId: (id: string) => ({ id }),
        reloadSchema: (schema: ExternalDataSourceSchema) => ({ schema }),
        resyncSchema: (schema: ExternalDataSourceSchema) => ({ schema }),
        setCanLoadMoreJobs: (canLoadMoreJobs: boolean) => ({ canLoadMoreJobs }),
    }),
    loaders(({ actions, values }) => ({
        source: [
            null as ExternalDataStripeSource | null,
            {
                loadSource: async () => {
                    return await api.externalDataSources.get(values.sourceId)
                },
                updateSchema: async (schema: ExternalDataSourceSchema) => {
                    // Optimistic UI updates before sending updates to the backend
                    const clonedSource = JSON.parse(JSON.stringify(values.source)) as ExternalDataStripeSource
                    const schemaIndex = clonedSource.schemas.findIndex((n) => n.id === schema.id)
                    clonedSource.schemas[schemaIndex] = schema
                    actions.loadSourceSuccess(clonedSource)

                    const updatedSchema = await api.externalDataSchemas.update(schema.id, schema)

                    const source = values.source
                    if (schemaIndex !== undefined) {
                        source!.schemas[schemaIndex] = updatedSchema
                    }

                    return source
                },
            },
        ],
        jobs: [
            [] as ExternalDataJob[],
            {
                loadJobs: async () => {
                    if (values.jobs.length === 0) {
                        return await api.externalDataSources.jobs(values.sourceId, null, null)
                    }

                    const newJobs = await api.externalDataSources.jobs(values.sourceId, null, values.jobs[0].created_at)
                    return [...newJobs, ...values.jobs]
                },
                loadMoreJobs: async () => {
                    const hasJobs = values.jobs.length >= 0
                    if (hasJobs) {
                        const lastJobCreatedAt = values.jobs[values.jobs.length - 1].created_at
                        const oldJobs = await api.externalDataSources.jobs(values.sourceId, lastJobCreatedAt, null)

                        if (oldJobs.length === 0) {
                            actions.setCanLoadMoreJobs(false)
                            return values.jobs
                        }

                        return [...values.jobs, ...oldJobs]
                    }

                    return values.jobs
                },
            },
        ],
    })),
    reducers(({ props }) => ({
        sourceId: [
            props.id,
            {
                setSourceId: (_, { id }) => id,
            },
        ],
        canLoadMoreJobs: [
            true as boolean,
            {
                setCanLoadMoreJobs: (_, { canLoadMoreJobs }) => canLoadMoreJobs,
                setSourceId: () => true,
            },
        ],
    })),

    listeners(({ values, actions, cache }) => ({
        loadSourceSuccess: () => {
            clearTimeout(cache.sourceRefreshTimeout)

            cache.sourceRefreshTimeout = setTimeout(() => {
                actions.loadSource()
            }, REFRESH_INTERVAL)
        },
        loadSourceFailure: () => {
            clearTimeout(cache.sourceRefreshTimeout)

            cache.sourceRefreshTimeout = setTimeout(() => {
                actions.loadSource()
            }, REFRESH_INTERVAL)
        },
        loadJobsSuccess: () => {
            clearTimeout(cache.jobsRefreshTimeout)

            cache.jobsRefreshTimeout = setTimeout(() => {
                actions.loadJobs()
            }, REFRESH_INTERVAL)
        },
        loadJobsFailure: () => {
            clearTimeout(cache.jobsRefreshTimeout)

            cache.jobsRefreshTimeout = setTimeout(() => {
                actions.loadJobs()
            }, REFRESH_INTERVAL)
        },
        reloadSchema: async ({ schema }) => {
            // Optimistic UI updates before sending updates to the backend
            const clonedSource = JSON.parse(JSON.stringify(values.source)) as ExternalDataStripeSource
            const schemaIndex = clonedSource.schemas.findIndex((n) => n.id === schema.id)
            clonedSource.status = 'Running'
            clonedSource.schemas[schemaIndex].status = 'Running'

            actions.loadSourceSuccess(clonedSource)

            try {
                await api.externalDataSchemas.reload(schema.id)

                posthog.capture('schema reloaded', { sourceType: clonedSource.source_type })
            } catch (e: any) {
                if (e.message) {
                    lemonToast.error(e.message)
                } else {
                    lemonToast.error('Cant reload schema at this time')
                }
            }
        },
        resyncSchema: async ({ schema }) => {
            // Optimistic UI updates before sending updates to the backend
            const clonedSource = JSON.parse(JSON.stringify(values.source)) as ExternalDataStripeSource
            const schemaIndex = clonedSource.schemas.findIndex((n) => n.id === schema.id)
            clonedSource.status = 'Running'
            clonedSource.schemas[schemaIndex].status = 'Running'

            actions.loadSourceSuccess(clonedSource)

            try {
                await api.externalDataSchemas.resync(schema.id)

                posthog.capture('schema resynced', { sourceType: clonedSource.source_type })
            } catch (e: any) {
                if (e.message) {
                    lemonToast.error(e.message)
                } else {
                    lemonToast.error('Cant refresh schema at this time')
                }
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSource()
        actions.loadJobs()
    }),
])
