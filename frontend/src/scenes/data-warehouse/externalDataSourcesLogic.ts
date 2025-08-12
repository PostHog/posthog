import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api, { ApiMethodOptions, PaginatedResponse } from 'lib/api'
import posthog from 'posthog-js'
import { DataModelingJob, ExternalDataJob, ExternalDataSource } from '~/types'

import type { externalDataSourcesLogicType } from './externalDataSourcesLogicType'

export const externalDataSourcesLogic = kea<externalDataSourcesLogicType>([
    path(['scenes', 'data-warehouse', 'externalDataSourcesLogic']),
    actions({
        abortAnyRunningQuery: true,
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
                            values.dataWarehouseSources?.results.map((s) =>
                                s.id === updatedSource.id ? updatedSource : s
                            ) || [],
                    }
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

export const fetchExternalDataSourceJobs = async (
    sourceId: string,
    before?: string | null,
    after?: string | null
): Promise<ExternalDataJob[]> => {
    const res: unknown = await api.externalDataSources.jobs(sourceId, before ?? null, after ?? null)
    return (Array.isArray(res) ? res : (res as any)?.results || []) as ExternalDataJob[]
}

export const fetchMaterializationJobs = async (
    savedQueryId: string,
    // TODO: Currently limiting to 10 results per materialization job. Revisit if this threshold needs to be adjusted.
    pageSize: number = 10,
    offset: number = 0
): Promise<DataModelingJob[]> => {
    const res = await api.dataWarehouseSavedQueries.dataWarehouseDataModelingJobs.list(savedQueryId, pageSize, offset)
    return res.results || []
}

const DATA_WAREHOUSE_CONFIG = {
    recentActivityDays: 7,
    maxJobsPerSource: 50,
    maxJobsPerView: 25,
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
}

const createConcurrencyLimiter = (maxConcurrency: number) => {
    let running = 0
    const queue: (() => void)[] = []

    return async <T>(fn: () => Promise<T>): Promise<T> => {
        return new Promise((resolve, reject) => {
            const execute = async (): Promise<void> => {
                running++
                try {
                    const result = await fn()
                    resolve(result)
                } catch (error) {
                    reject(error)
                } finally {
                    running--
                    if (queue.length > 0) {
                        const next = queue.shift()!
                        next()
                    }
                }
            }

            if (running < maxConcurrency) {
                execute()
            } else {
                queue.push(execute)
            }
        })
    }
}

export const fetchRecentActivity = async (
    dataSources: ExternalDataSource[],
    materializedViews: any[],
    recentDays: number = DATA_WAREHOUSE_CONFIG.recentActivityDays
): Promise<UnifiedRecentActivity[]> => {
    const cutoffDate = new Date()
    cutoffDate.setDate(cutoffDate.getDate() - recentDays)

    const limiter = createConcurrencyLimiter(DATA_WAREHOUSE_CONFIG.maxConcurrentRequests)

    const [schemaResults, materializationResults] = await Promise.all([
        Promise.all(
            dataSources.map((source) =>
                limiter(async () => {
                    const allJobs: ExternalDataJob[] = []
                    let hasMore = true
                    let lastJobTimestamp: string | null = null
                    let recentJobsFound = 0

                    while (hasMore && allJobs.length < DATA_WAREHOUSE_CONFIG.maxJobsPerSource) {
                        try {
                            const jobs = await fetchExternalDataSourceJobs(source.id, lastJobTimestamp, null)
                            if (jobs.length === 0) {
                                break
                            }
                            const recentJobs = jobs.filter((job) => new Date(job.created_at) >= cutoffDate)
                            recentJobsFound += recentJobs.length
                            allJobs.push(...recentJobs)

                            const oldestJob = jobs[jobs.length - 1]

                            if (oldestJob && new Date(oldestJob.created_at) < cutoffDate) {
                                hasMore = false
                            } else if (recentJobsFound >= DATA_WAREHOUSE_CONFIG.batchSize) {
                                hasMore = false
                            } else {
                                lastJobTimestamp = oldestJob?.created_at || null
                            }
                        } catch (error) {
                            posthog.captureException(error)
                            hasMore = false
                        }
                    }

                    return allJobs.map((job) => ({
                        id: job.id,
                        name: job.schema.name,
                        type: 'Data Sync' as const,
                        status: job.status,
                        created_at: job.created_at,
                        rowCount: job.rows_synced,
                        sourceName: source.source_type,
                    }))
                })
            )
        ),

        Promise.all(
            materializedViews.map((view) =>
                limiter(async () => {
                    try {
                        const jobs = await fetchMaterializationJobs(view.id, DATA_WAREHOUSE_CONFIG.maxJobsPerView)
                        return jobs
                            .filter((job) => new Date(job.created_at) >= cutoffDate)
                            .map((job) => ({
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
            )
        ),
    ])

    const allActivities = [...schemaResults.flat(), ...materializationResults.flat()]
    return allActivities.sort((a, b) => new Date(b.created_at).valueOf() - new Date(a.created_at).valueOf())
}

export const fetchTotalRowsProcessed = async (
    dataSources: ExternalDataSource[],
    materializedViews: any[]
): Promise<number> => {
    const limiter = createConcurrencyLimiter(DATA_WAREHOUSE_CONFIG.maxConcurrentRequests)
    let totalRows = 0

    const [schemaResults, materializationResults] = await Promise.all([
        // get ALL schema sync jobs (no limit) and sum their rows_synced
        Promise.all(
            dataSources.map((source) =>
                limiter(async () => {
                    try {
                        const allJobs: ExternalDataJob[] = []
                        let hasMore = true
                        let lastJobTimestamp: string | null = null

                        while (hasMore && allJobs.length < DATA_WAREHOUSE_CONFIG.maxJobsPerSource) {
                            const jobs = await fetchExternalDataSourceJobs(source.id, lastJobTimestamp, null)
                            if (jobs.length === 0) {
                                break
                            }

                            allJobs.push(...jobs)
                            lastJobTimestamp = jobs[jobs.length - 1]?.created_at || null

                            if (allJobs.length >= DATA_WAREHOUSE_CONFIG.maxJobsPerSource) {
                                hasMore = false
                            }
                        }

                        return allJobs.reduce((sum, job) => sum + (job.rows_synced || 0), 0)
                    } catch (error) {
                        posthog.captureException(error)
                        return 0
                    }
                })
            )
        ),

        // get ALL materialization jobs (no limit) and sum their rows_materialized
        Promise.all(
            materializedViews.map((view) =>
                limiter(async () => {
                    try {
                        const jobs = await fetchMaterializationJobs(view.id, DATA_WAREHOUSE_CONFIG.maxJobsPerView)
                        return jobs.reduce((sum, job) => sum + (job.rows_materialized || 0), 0)
                    } catch (error) {
                        posthog.captureException(error)
                        return 0
                    }
                })
            )
        ),
    ])

    totalRows += schemaResults.reduce((sum, sourceTotal) => sum + sourceTotal, 0)
    totalRows += materializationResults.reduce((sum, viewTotal) => sum + viewTotal, 0)

    return totalRows
}
