import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import posthog from 'posthog-js'
import { getErrorsForFields, SOURCE_DETAILS } from 'scenes/data-warehouse/new/sourceWizardLogic'

import { ExternalDataJob, ExternalDataSchemaStatus, ExternalDataSource, ExternalDataSourceSchema } from '~/types'

import { dataWarehouseSourceSceneLogic } from '../DataWarehouseSourceScene'
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
        deleteTable: (schema: ExternalDataSourceSchema) => ({ schema }),
        setCanLoadMoreJobs: (canLoadMoreJobs: boolean) => ({ canLoadMoreJobs }),
        setIsProjectTime: (isProjectTime: boolean) => ({ isProjectTime }),
    }),
    loaders(({ actions, values }) => ({
        source: [
            null as ExternalDataSource | null,
            {
                loadSource: async () => {
                    return await api.externalDataSources.get(values.sourceId)
                },
                updateSchema: async (schema: ExternalDataSourceSchema, breakpoint) => {
                    await breakpoint(500)
                    // Optimistic UI updates before sending updates to the backend
                    const clonedSource = JSON.parse(JSON.stringify(values.source)) as ExternalDataSource
                    const schemaIndex = clonedSource.schemas.findIndex((n) => n.id === schema.id)
                    clonedSource.schemas[schemaIndex] = schema
                    actions.loadSourceSuccess(clonedSource)

                    const updatedSchema = await api.externalDataSchemas.update(schema.id, {
                        ...schema,
                    })

                    const source = values.source
                    if (schemaIndex !== undefined) {
                        source!.schemas[schemaIndex] = updatedSchema
                    }

                    return source
                },
                updateSource: async (source: ExternalDataSource) => {
                    const updatedSource = await api.externalDataSources.update(values.sourceId, source)
                    actions.loadSourceSuccess(updatedSource)
                    return updatedSource
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
        isProjectTime: [
            false as boolean,
            {
                setIsProjectTime: (_, { isProjectTime }) => isProjectTime,
            },
        ],
    })),
    selectors({
        sourceFieldConfig: [
            (s) => [s.source],
            (source) => {
                if (!source) {
                    return null
                }

                return SOURCE_DETAILS[source.source_type]
            },
        ],
    }),
    forms(({ values, actions }) => ({
        sourceConfig: {
            defaults: {} as Record<string, any>,
            errors: (sourceValues) => {
                return getErrorsForFields(values.sourceFieldConfig?.fields ?? [], sourceValues as any)
            },
            submit: async ({ payload = {} }) => {
                const newJobInputs = {
                    ...values.source?.job_inputs,
                    ...payload,
                }

                // Handle file uploads
                const sourceFieldConfig = values.sourceFieldConfig
                if (sourceFieldConfig?.fields) {
                    for (const field of sourceFieldConfig.fields) {
                        if (field.type === 'file-upload' && payload[field.name]) {
                            try {
                                // Assumes we're loading a JSON file
                                const loadedFile: string = await new Promise((resolve, reject) => {
                                    const fileReader = new FileReader()
                                    fileReader.onload = (e) => resolve(e.target?.result as string)
                                    fileReader.onerror = (e) => reject(e)
                                    fileReader.readAsText(payload[field.name][0])
                                })
                                newJobInputs[field.name] = JSON.parse(loadedFile)
                            } catch (e) {
                                lemonToast.error('File is not valid')
                                return
                            }
                        }
                    }
                }

                try {
                    const updatedSource = await api.externalDataSources.update(values.sourceId, {
                        job_inputs: newJobInputs,
                    })
                    actions.loadSourceSuccess(updatedSource)
                    lemonToast.success('Source updated')
                } catch (e: any) {
                    if (e.message) {
                        lemonToast.error(e.message)
                    } else {
                        lemonToast.error('Cant update source at this time')
                    }
                }
            },
        },
    })),
    listeners(({ values, actions, cache, props }) => ({
        loadSourceSuccess: () => {
            clearTimeout(cache.sourceRefreshTimeout)

            cache.sourceRefreshTimeout = setTimeout(() => {
                actions.loadSource()
            }, REFRESH_INTERVAL)

            dataWarehouseSourceSceneLogic
                .findMounted({
                    id: `managed-${props.id}`,
                })
                ?.actions.setBreadcrumbName(values.source?.source_type ?? 'Source')
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
            const clonedSource = JSON.parse(JSON.stringify(values.source)) as ExternalDataSource
            const schemaIndex = clonedSource.schemas.findIndex((n) => n.id === schema.id)
            clonedSource.status = 'Running'
            clonedSource.schemas[schemaIndex].status = ExternalDataSchemaStatus.Running

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
            const clonedSource = JSON.parse(JSON.stringify(values.source)) as ExternalDataSource
            const schemaIndex = clonedSource.schemas.findIndex((n) => n.id === schema.id)
            clonedSource.status = 'Running'
            clonedSource.schemas[schemaIndex].status = ExternalDataSchemaStatus.Running

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
        deleteTable: async ({ schema }) => {
            // Optimistic UI updates before sending updates to the backend
            const clonedSource = JSON.parse(JSON.stringify(values.source)) as ExternalDataSource
            const schemaIndex = clonedSource.schemas.findIndex((n) => n.id === schema.id)
            if (schemaIndex === -1) {
                lemonToast.error('Schema not found')
                return
            }
            clonedSource.schemas[schemaIndex].table = undefined
            clonedSource.schemas[schemaIndex].status = undefined
            clonedSource.schemas[schemaIndex].last_synced_at = undefined
            actions.loadSourceSuccess(clonedSource)

            try {
                await api.externalDataSchemas.delete_data(schema.id)

                posthog.capture('schema data deleted', { sourceType: clonedSource.source_type })
                lemonToast.success(`Data for ${schema.name} has been deleted`)
            } catch (e: any) {
                if (e.message) {
                    lemonToast.error(e.message)
                } else {
                    lemonToast.error("Can't delete data at this time")
                }
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSource()
        actions.loadJobs()
    }),
])
