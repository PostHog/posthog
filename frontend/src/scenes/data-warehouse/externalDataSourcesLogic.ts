import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api, { ApiMethodOptions, PaginatedResponse } from 'lib/api'
import posthog from 'posthog-js'
import { DataModelingJob, ExternalDataJob, ExternalDataSource } from '~/types'
import type { externalDataSourcesLogicType } from './externalDataSourcesLogicType'

const DATA_WAREHOUSE_CONFIG = {
    recentActivityDays: 7,
    maxJobsForMTD: 200,
} as const

const getMonthStartISO = (): string => {
    const now = new Date()
    return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1)).toISOString()
}

const sumMTDRows = (
    jobs: { created_at: string; rows_synced?: number; rows_materialized?: number }[],
    monthStartISO: string
): number => {
    return jobs
        .filter((job) => job.created_at >= monthStartISO)
        .reduce((sum, job) => sum + (job.rows_synced || job.rows_materialized || 0), 0)
}

export interface UnifiedRecentActivity {
    id: string
    name: string
    type: 'Materialization' | 'Data Sync'
    status: string
    created_at: string
    rowCount: number
    sourceName?: string
    sourceId?: string
}

export interface DashboardDataSource {
    id: string
    name: string
    type: 'Database' | 'API'
    status: string | null
    lastSync: string | null
    rowCount: number | null
    url: string
}

export const externalDataSourcesLogic = kea<externalDataSourcesLogicType>([
    path(['scenes', 'data-warehouse', 'externalDataSourcesLogic']),
    actions({
        abortAnyRunningQuery: true,
        loadTotalRowsProcessed: (materializedViews: any[]) => ({ materializedViews }),
        loadRecentActivity: (materializedViews: any[]) => ({ materializedViews }),
    }),
    loaders(({ cache, values, actions }) => ({
        dataWarehouseSources: [
            null as PaginatedResponse<ExternalDataSource> | null,
            {
                loadSources: async (_, breakpoint) => {
                    await breakpoint(300)
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
                    return {
                        ...values.dataWarehouseSources,
                        results:
                            values.dataWarehouseSources?.results.map((s: ExternalDataSource) =>
                                s.id === updatedSource.id ? updatedSource : s
                            ) || [],
                    }
                },
            },
        ],
        totalRowsProcessed: [
            0 as number,
            {
                loadTotalRowsProcessed: async ({ materializedViews }: { materializedViews: any[] }) => {
                    const dataSources = values.dataWarehouseSources?.results || []

                    const monthStartISO = getMonthStartISO()

                    const [schemaResults, materializationResults] = await Promise.all([
                        Promise.all(
                            dataSources.map(async (source: ExternalDataSource) => {
                                try {
                                    const jobs = await api.externalDataSources.jobs(source.id, monthStartISO, null)
                                    return sumMTDRows(jobs, monthStartISO)
                                } catch (error) {
                                    posthog.captureException(error)
                                    return 0
                                }
                            })
                        ),

                        Promise.all(
                            materializedViews.map(async (view: any) => {
                                try {
                                    const res = await api.dataWarehouseSavedQueries.dataWarehouseDataModelingJobs.list(
                                        view.id,
                                        DATA_WAREHOUSE_CONFIG.maxJobsForMTD,
                                        0
                                    )
                                    return sumMTDRows(res.results || [], monthStartISO)
                                } catch (error) {
                                    posthog.captureException(error)
                                    return 0
                                }
                            })
                        ),
                    ])

                    return [...schemaResults, ...materializationResults].reduce((sum, total) => sum + total, 0)
                },
            },
        ],
        recentActivity: [
            [] as UnifiedRecentActivity[],
            {
                loadRecentActivity: async ({ materializedViews }: { materializedViews: any[] }) => {
                    const dataSources = values.dataWarehouseSources?.results || []
                    const cutoffDate = new Date()
                    cutoffDate.setDate(cutoffDate.getDate() - DATA_WAREHOUSE_CONFIG.recentActivityDays)

                    const [schemaResults, materializationResults] = await Promise.all([
                        Promise.all(
                            dataSources.map(async (source: ExternalDataSource) => {
                                const allJobs: ExternalDataJob[] = []
                                let lastJobTimestamp: string | null = null

                                while (true) {
                                    try {
                                        const jobs: ExternalDataJob[] = await (async () => {
                                            const res: unknown = await api.externalDataSources.jobs(
                                                source.id,
                                                lastJobTimestamp ?? null,
                                                null
                                            )
                                            return (
                                                Array.isArray(res) ? res : (res as any)?.results || []
                                            ) as ExternalDataJob[]
                                        })()

                                        if (jobs.length === 0) {
                                            break
                                        }

                                        allJobs.push(...jobs)

                                        const oldestJob: ExternalDataJob | undefined = jobs[jobs.length - 1]
                                        lastJobTimestamp = oldestJob?.created_at || null
                                    } catch (error) {
                                        posthog.captureException(error)
                                        break
                                    }
                                }

                                return allJobs.map((job) => ({
                                    id: job.id,
                                    name: job.schema.name,
                                    type: 'Data Sync' as const,
                                    status: job.status,
                                    created_at: job.created_at,
                                    rowCount: job.rows_synced,
                                    sourceId: source.id,
                                    sourceName: source.source_type,
                                }))
                            })
                        ),

                        Promise.all(
                            materializedViews.map(async (view: any) => {
                                try {
                                    const res = await api.dataWarehouseSavedQueries.dataWarehouseDataModelingJobs.list(
                                        view.id,
                                        100,
                                        0
                                    )
                                    const jobs = res.results || []
                                    return jobs
                                        .filter((job: DataModelingJob) => new Date(job.created_at) >= cutoffDate)
                                        .map((job: DataModelingJob) => ({
                                            id: job.id,
                                            name: view.name,
                                            type: 'Materialization' as const,
                                            status: job.status,
                                            created_at: job.created_at,
                                            rowCount: job.rows_materialized,
                                        }))
                                } catch (error) {
                                    posthog.captureException(error)
                                    return []
                                }
                            })
                        ),
                    ])

                    const allActivities = [...schemaResults.flat(), ...materializationResults.flat()]
                    return allActivities.sort(
                        (a, b) => new Date(b.created_at).valueOf() - new Date(a.created_at).valueOf()
                    )
                },
            },
        ],
    })),
    reducers(({ cache }) => ({
        dataWarehouseSourcesLoading: [
            false as boolean,
            {
                loadSources: () => true,
                loadSourcesFailure: () => cache.abortController !== null,
                loadSourcesSuccess: () => cache.abortController !== null,
            },
        ],
    })),
    listeners(({ cache }) => ({
        abortAnyRunningQuery: () => {
            if (cache.abortController) {
                cache.abortController.abort()
                cache.abortController = null
            }
        },
    })),
])
