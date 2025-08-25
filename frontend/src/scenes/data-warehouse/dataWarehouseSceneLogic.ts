import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api, { PaginatedResponse } from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { billingLogic } from 'scenes/billing/billingLogic'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { urls } from 'scenes/urls'

import { DatabaseSchemaDataWarehouseTable } from '~/queries/schema/schema-general'
import {
    DataWarehouseActivityRecord,
    DataWarehouseDailyRowsBreakdown,
    DataWarehouseDailyRowsSyncedData,
    DataWarehouseSavedQuery,
    DataWarehouseSourceRowCount,
    DataWarehouseSyncJobRun,
} from '~/types'

import type { dataWarehouseSceneLogicType } from './dataWarehouseSceneLogicType'
import { externalDataSourcesLogic } from './externalDataSourcesLogic'
import { dataWarehouseViewsLogic } from './saved_queries/dataWarehouseViewsLogic'

const REFRESH_INTERVAL = 10000

const ERROR_PATTERNS = {
    AUTH: /auth|credential|permission|unauthorized|forbidden|invalid.*token|expired.*token|access.*denied/i,
    RATE_LIMIT: /rate.*limit|429|quota.*exceeded|too.*many.*requests|throttle/i,
    WARNING: /slow|performance|timeout.*warning|retry.*limit/i,
}

const determineSeverity = (error: string | null): 'critical' | 'warning' => {
    if (!error) {
        return 'critical'
    }
    return ERROR_PATTERNS.WARNING.test(error) ? 'warning' : 'critical'
}

const getActionType = (error: string | null): 'update_credentials' | 'adjust_frequency' | 'retry_sync' => {
    if (!error) {
        return 'retry_sync'
    }
    if (ERROR_PATTERNS.AUTH.test(error)) {
        return 'update_credentials'
    }
    if (ERROR_PATTERNS.RATE_LIMIT.test(error)) {
        return 'adjust_frequency'
    }
    return 'retry_sync'
}

export const dataWarehouseSceneLogic = kea<dataWarehouseSceneLogicType>([
    path(['scenes', 'data-warehouse', 'dataWarehouseSceneLogic']),
    connect(() => ({
        values: [
            databaseTableListLogic,
            ['dataWarehouseTables', 'views'],
            externalDataSourcesLogic,
            ['dataWarehouseSources', 'dataWarehouseSourcesLoading'],
            billingLogic,
            ['billingPeriodUTC', 'billing'],
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueryMapById'],
        ],
        actions: [
            databaseTableListLogic,
            ['loadDatabase'],
            externalDataSourcesLogic,
            ['loadSources', 'loadSourcesSuccess'],
        ],
    })),
    actions({
        loadMoreRecentActivity: true,
        setActivityCurrentPage: (page: number) => ({ page }),
        checkAutoLoadMore: true,
        loadDailyBreakdown: true,
        setSelectedDate: (date: string) => ({ date }),
        setSelectedRows: (rows: number | null) => ({ rows }),
        clearModal: true,
    }),
    loaders(() => ({
        totalRowsStats: [
            {} as DataWarehouseSourceRowCount,
            {
                loadTotalRowsStats: async () => {
                    return await api.dataWarehouse.totalRowsStats()
                },
            },
        ],
        recentActivityResponse: [
            null as PaginatedResponse<DataWarehouseActivityRecord> | null,
            {
                loadRecentActivityResponse: async () => {
                    return await api.dataWarehouse.recentActivity({ limit: 20, offset: 0 })
                },
            },
        ],
        dailyBreakdownData: [
            null as DataWarehouseDailyRowsBreakdown | null,
            {
                loadDailyBreakdown: async () => {
                    return await api.dataWarehouse.breakdownOfRowsSyncedByDayInBillingPeriod()
                },
            },
        ],
    })),
    reducers(() => ({
        activityCurrentPage: [
            1 as number,
            {
                setActivityCurrentPage: (_, { page }) => page,
                loadRecentActivityResponse: () => 1,
            },
        ],
        recentActivityMoreLoading: [
            false as boolean,
            {
                loadMoreRecentActivity: () => true,
                loadRecentActivityResponseSuccess: () => false,
            },
        ],
        selectedDate: [
            null as string | null,
            {
                setSelectedDate: (_, { date }) => date,
                clearModal: () => null,
            },
        ],
        selectedRows: [
            null as number | null,
            {
                setSelectedRows: (_, { rows }) => rows,
                clearModal: () => null,
            },
        ],
    })),
    selectors({
        recentActivity: [
            (s) => [s.recentActivityResponse],
            (response: PaginatedResponse<DataWarehouseActivityRecord> | null): DataWarehouseActivityRecord[] => {
                return response?.results || []
            },
        ],
        recentActivityHasMore: [
            (s) => [s.recentActivityResponse],
            (response: PaginatedResponse<DataWarehouseActivityRecord> | null): boolean => {
                return !!response?.next
            },
        ],
        selfManagedTables: [
            (s) => [s.dataWarehouseTables],
            (dataWarehouseTables): DatabaseSchemaDataWarehouseTable[] => {
                return dataWarehouseTables.filter((table) => !table.source)
            },
        ],
        computedAllSources: [
            (s) => [
                s.dataWarehouseSources,
                s.recentActivity,
                s.selfManagedTables,
                s.billingPeriodUTC,
                s.totalRowsStats,
            ],
            (dataWarehouseSources, recentActivity, selfManagedTables, billingPeriodUTC, totalRowsStats) => {
                const managed = (dataWarehouseSources?.results || []).map((source) => {
                    const activities =
                        recentActivity?.filter(
                            (a) =>
                                !billingPeriodUTC ||
                                !billingPeriodUTC.start ||
                                !billingPeriodUTC.end ||
                                (dayjs(a.created_at).isAfter(billingPeriodUTC.start.subtract(1, 'millisecond')) &&
                                    dayjs(a.created_at).isBefore(billingPeriodUTC.end))
                        ) || []
                    const lastSync =
                        activities.sort((a, b) => dayjs(b.created_at).valueOf() - dayjs(a.created_at).valueOf())[0]
                            ?.created_at || null
                    return {
                        id: source.id,
                        name: source.source_type,
                        status: source.status,
                        lastSync,
                        rowCount: totalRowsStats?.breakdown_of_rows_by_source?.[source.id] ?? 0,
                        url: urls.dataWarehouseSource(`managed-${source.id}`),
                    }
                })

                const selfManaged = (selfManagedTables || []).map((table) => ({
                    id: table.id,
                    name: table.name,
                    status: null,
                    lastSync: null,
                    rowCount: table.row_count ?? null,
                    url: urls.dataWarehouseSource(`self-managed-${table.id}`),
                }))

                return [...managed, ...selfManaged]
            },
        ],
        activityPaginationState: [
            (s) => [s.recentActivity, s.activityCurrentPage],
            (recentActivity, activityCurrentPage) => {
                const pageSize = 5
                const startIndex = (activityCurrentPage - 1) * pageSize
                const endIndex = Math.min(startIndex + pageSize, recentActivity.length)
                const pageCount = Math.ceil(recentActivity.length / pageSize)

                return {
                    currentPage: activityCurrentPage,
                    pageCount,
                    dataSourcePage: recentActivity.slice(startIndex, endIndex),
                    currentStartIndex: startIndex,
                    currentEndIndex: endIndex,
                    entryCount: recentActivity.length,
                    isOnLastPage: activityCurrentPage === pageCount,
                    hasDataOnCurrentPage: endIndex > startIndex,
                }
            },
        ],
        materializedViews: [
            (s) => [s.views, s.dataWarehouseSavedQueryMapById],
            (
                views: DatabaseSchemaDataWarehouseTable[],
                dataWarehouseSavedQueryMapById: Record<string, DataWarehouseSavedQuery>
            ) => {
                return views
                    .filter((view) => dataWarehouseSavedQueryMapById[view.id]?.status)
                    .map((view) => ({
                        ...view,
                        type: 'materialized_view',
                        last_run_at: dataWarehouseSavedQueryMapById[view.id]?.last_run_at,
                        status: dataWarehouseSavedQueryMapById[view.id]?.status,
                    }))
            },
        ],
        dailyRowsSyncedData: [
            (s) => [s.dailyBreakdownData],
            (dailyBreakdownData): DataWarehouseDailyRowsSyncedData[] => {
                if (!dailyBreakdownData?.billing_available) {
                    return []
                }

                const billingStart = dayjs(dailyBreakdownData.billing_period_start)
                const billingEnd = dayjs(dailyBreakdownData.billing_period_end)
                const today = dayjs()

                if (!billingStart.isValid() || !billingEnd.isValid()) {
                    return []
                }

                const dailyData = new Map<string, number | null>()
                for (let d = billingStart; d.isSameOrBefore(billingEnd, 'day'); d = d.add(1, 'day')) {
                    dailyData.set(d.format('YYYY-MM-DD'), d.isAfter(today, 'day') ? null : 0)
                }

                dailyBreakdownData.breakdown_of_rows_by_day?.forEach(({ date, rows_synced }) => {
                    if (dayjs(date).isSameOrBefore(today, 'day')) {
                        dailyData.set(date, rows_synced)
                    }
                })

                return Array.from(dailyData.entries())
                    .map(([date, rows_synced]) => ({ date, rows_synced }))
                    .sort((a, b) => dayjs(a.date).unix() - dayjs(b.date).unix())
            },
        ],
        hasData: [
            (s) => [s.dailyRowsSyncedData],
            (dailyData) => dailyData.some((item) => item.rows_synced && item.rows_synced > 0),
        ],
        totalRowsInPeriod: [
            (s) => [s.dailyRowsSyncedData],
            (dailyData) => dailyData.reduce((sum, item) => sum + (item.rows_synced || 0), 0),
        ],
        sourceBreakdown: [
            (s) => [s.dailyBreakdownData],
            (dailyBreakdownData) => {
                if (!dailyBreakdownData?.breakdown_of_rows_by_day) {
                    return []
                }

                const sourceStats: Record<string, { rows: number; jobs: number }> = {}

                dailyBreakdownData.breakdown_of_rows_by_day.forEach((day) => {
                    day.runs?.forEach((run) => {
                        const source = run.source_type || 'Unknown'
                        if (!sourceStats[source]) {
                            sourceStats[source] = { rows: 0, jobs: 0 }
                        }
                        sourceStats[source].rows += run.rows_synced || 0
                        sourceStats[source].jobs += 1
                    })
                })

                return Object.entries(sourceStats)
                    .map(([source, stats]) => ({ source, ...stats }))
                    .sort((a, b) => b.rows - a.rows)
            },
        ],
        selectedDateBreakdown: [
            (s) => [s.dailyBreakdownData, s.selectedDate],
            (dailyBreakdownData, selectedDate) => {
                if (!dailyBreakdownData?.breakdown_of_rows_by_day || !selectedDate) {
                    return null
                }
                return (
                    dailyBreakdownData.breakdown_of_rows_by_day.find((breakdown) => breakdown.date === selectedDate) ||
                    null
                )
            },
        ],
        selectedDateRunsBySource: [
            (s) => [s.selectedDateBreakdown],
            (dateBreakdown) => {
                if (!dateBreakdown?.runs) {
                    return null
                }

                const runsBySource: Record<string, { count: number; rows: number; runs: DataWarehouseSyncJobRun[] }> =
                    {}

                dateBreakdown.runs.forEach((run) => {
                    const source = run.source_type || 'Unknown'
                    if (!runsBySource[source]) {
                        runsBySource[source] = { count: 0, rows: 0, runs: [] }
                    }
                    runsBySource[source].count += 1
                    runsBySource[source].rows += run.rows_synced || 0
                    runsBySource[source].runs.push(run)
                })

                return Object.entries(runsBySource)
                    .map(([source, data]) => ({
                        source,
                        count: data.count,
                        rows: data.rows,
                        runs: data.runs.sort((a, b) => dayjs(b.created_at).valueOf() - dayjs(a.created_at).valueOf()),
                    }))
                    .sort((a, b) => b.rows - a.rows)
            },
        ],
        actionableIssues: [
            (s) => [s.recentActivity, s.dataWarehouseSources, s.dataWarehouseSavedQueryMapById],
            (recentActivity, dataWarehouseSources, dataWarehouseSavedQueryMapById) => {
                const issues: Array<{
                    id: string
                    type: 'data_source' | 'materialization'
                    severity: 'critical' | 'warning'
                    title: string
                    description: string
                    timestamp: string
                    actionType: string
                    actionUrl: string
                    count?: number
                }> = []
                // handle materialized view failures from recent activity
                const materializedViewActivities = recentActivity
                    .filter((activity) => activity.type === 'Materialized view')
                    .reduce(
                        (groups, activity) => {
                            const key = activity.name || 'unknown'
                            groups[key] = groups[key] || []
                            groups[key].push(activity)
                            return groups
                        },
                        {} as Record<string, typeof recentActivity>
                    )

                for (const [viewName, activities] of Object.entries(materializedViewActivities)) {
                    const latestActivity = activities.sort(
                        (a, b) => dayjs(b.created_at).valueOf() - dayjs(a.created_at).valueOf()
                    )[0]
                    // only create issues if the most recent run failed
                    if (latestActivity.status !== 'Failed' && !latestActivity.latest_error) {
                        continue
                    }

                    const materializedView = Object.values(dataWarehouseSavedQueryMapById).find(
                        (query) => query.name === latestActivity.name
                    )

                    issues.push({
                        id: `materialization-${latestActivity.id}`,
                        type: 'materialization',
                        severity: 'critical',
                        title: `${viewName} (Materialized View)`,
                        description: latestActivity.latest_error || 'Materialization failed',
                        timestamp: latestActivity.created_at,
                        actionType: 'view_materialization',
                        actionUrl: urls.sqlEditor(
                            undefined,
                            materializedView?.id,
                            undefined,
                            undefined,
                            'materialization'
                        ),
                    })
                }

                // handle data source failures from source status directly, not from recent activity
                const sourcesWithErrors =
                    dataWarehouseSources?.results?.filter(
                        (source) => source.latest_error && source.status === 'Error'
                    ) || []

                sourcesWithErrors.forEach((source) => {
                    issues.push({
                        id: `source-status-${source.id}`,
                        type: 'data_source',
                        severity: determineSeverity(source.latest_error),
                        title: source.source_type,
                        description: source.latest_error || 'Sync failed',
                        timestamp:
                            (typeof source.last_run_at === 'string'
                                ? source.last_run_at
                                : source.last_run_at?.toISOString()) || new Date().toISOString(),
                        actionType: getActionType(source.latest_error),
                        actionUrl: urls.dataWarehouseSource(`managed-${source.id}`),
                    })
                })

                return issues.sort((a, b) => dayjs(b.timestamp).valueOf() - dayjs(a.timestamp).valueOf())
            },
        ],
    }),
    listeners(({ cache, values, actions }) => ({
        setActivityCurrentPage: () => {
            actions.checkAutoLoadMore()
        },
        checkAutoLoadMore: () => {
            const paginationState = values.activityPaginationState
            const { isOnLastPage, hasDataOnCurrentPage } = paginationState
            const { recentActivityHasMore, recentActivityResponseLoading } = values

            if (isOnLastPage && hasDataOnCurrentPage && recentActivityHasMore && !recentActivityResponseLoading) {
                actions.loadMoreRecentActivity()
            }
        },
        loadMoreRecentActivity: async () => {
            try {
                const currentData = values.recentActivity
                const response = await api.dataWarehouse.recentActivity({
                    limit: 20,
                    offset: currentData.length,
                })
                const newData = [...currentData, ...(response.results || [])]
                const newResponse = { ...response, results: newData }

                actions.loadRecentActivityResponseSuccess(newResponse)
            } catch (error) {
                posthog.captureException(error)
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
    })),
    afterMount(({ actions }) => {
        actions.loadSources(null)
        actions.loadRecentActivityResponse()
        actions.loadTotalRowsStats()
        actions.loadDailyBreakdown()
    }),
    beforeUnmount(({ cache }) => {
        clearTimeout(cache.refreshTimeout)
    }),
])
