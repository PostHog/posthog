import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api, { ApiMethodOptions, PaginatedResponse } from 'lib/api'
import posthog from 'posthog-js'
import { DataModelingJob, ExternalDataJob, ExternalDataSource } from '~/types'
import type { externalDataSourcesLogicType } from './externalDataSourcesLogicType'

const DATA_WAREHOUSE_CONFIG = {
    recentActivityDays: 7,
    maxConcurrentRequests: 5,
    batchSize: 20,
} as const

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

                    // Calculate start of current month in user's timezone
                    const now = new Date()
                    const startOfMonth = new Date(now.getFullYear(), now.getMonth(), 1)
                    const monthStartISO = startOfMonth.toISOString()

                    let totalRows = 0

                    const [schemaResults, materializationResults] = await Promise.all([
                        // Get MTD schema sync jobs and sum their rows_synced
                        Promise.all(
                            dataSources.map(async (source: ExternalDataSource) => {
                                try {
                                    const allJobs: ExternalDataJob[] = []
                                    let lastJobTimestamp: string | null = null

                                    while (true) {
                                        const res: unknown = await api.externalDataSources.jobs(
                                            source.id,
                                            lastJobTimestamp ?? null,
                                            null
                                        )
                                        const jobs = (
                                            Array.isArray(res) ? res : (res as any)?.results || []
                                        ) as ExternalDataJob[]

                                        if (jobs.length === 0) {
                                            break
                                        }

                                        // Filter jobs to only include those from this month
                                        const monthJobs = jobs.filter((job) => job.created_at >= monthStartISO)
                                        allJobs.push(...monthJobs)

                                        // If we've hit jobs older than the start of the month, we can stop
                                        const oldestJob = jobs[jobs.length - 1]
                                        if (oldestJob && oldestJob.created_at < monthStartISO) {
                                            break
                                        }

                                        lastJobTimestamp = oldestJob?.created_at || null
                                    }

                                    return allJobs.reduce((sum, job) => sum + (job.rows_synced || 0), 0)
                                } catch (error) {
                                    posthog.captureException(error)
                                    return 0
                                }
                            })
                        ),

                        // Get MTD materialization jobs and sum their rows_materialized
                        Promise.all(
                            materializedViews.map(async (view: any) => {
                                try {
                                    const res = await api.dataWarehouseSavedQueries.dataWarehouseDataModelingJobs.list(
                                        view.id,
                                        100, // Reasonable limit for MTD
                                        0
                                    )
                                    const jobs = res.results || []

                                    // Filter to MTD jobs only
                                    const monthJobs = jobs.filter(
                                        (job: DataModelingJob) => job.created_at >= monthStartISO
                                    )

                                    return monthJobs.reduce(
                                        (sum: number, job: DataModelingJob) => sum + (job.rows_materialized || 0),
                                        0
                                    )
                                } catch (error) {
                                    posthog.captureException(error)
                                    return 0
                                }
                            })
                        ),
                    ])

                    totalRows += schemaResults.reduce((sum, sourceTotal) => sum + sourceTotal, 0)
                    totalRows += materializationResults.reduce((sum, viewTotal) => sum + viewTotal, 0)

                    return totalRows
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
                                        100, // Reasonable limit for MTD
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
