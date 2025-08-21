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
    BillingPeriod,
    DataWarehouseActivityRecord,
    DataWarehouseDailyRowsBreakdown,
    DataWarehouseDashboardDataSource,
    DataWarehouseSourceRowCount,
    ExternalDataSource,
} from '~/types'

import type { dataWarehouseSceneLogicType } from './dataWarehouseSceneLogicType'
import { externalDataSourcesLogic } from './externalDataSourcesLogic'
import { dataWarehouseViewsLogic } from './saved_queries/dataWarehouseViewsLogic'

export interface DailyRowsSyncedData {
    date: string
    rows_synced: number | null
}

const REFRESH_INTERVAL = 10000

export const dataWarehouseSceneLogic = kea<dataWarehouseSceneLogicType>([
    path(['scenes', 'data-warehouse', 'dataWarehouseSceneLogic']),
    connect(() => ({
        values: [
            databaseTableListLogic,
            ['dataWarehouseTables', 'views', 'databaseLoading'],
            externalDataSourcesLogic,
            ['dataWarehouseSources', 'dataWarehouseSourcesLoading'],
            billingLogic,
            ['billingPeriodUTC'],
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
            (
                dataWarehouseSources: PaginatedResponse<ExternalDataSource> | null,
                recentActivity: DataWarehouseActivityRecord[],
                selfManagedTables: DatabaseSchemaDataWarehouseTable[],
                billingPeriodUTC: BillingPeriod,
                totalRowsStats: DataWarehouseSourceRowCount
            ): DataWarehouseDashboardDataSource[] => {
                const billingPeriodStart = billingPeriodUTC?.start
                const billingPeriodEnd = billingPeriodUTC?.end

                const managed: DataWarehouseDashboardDataSource[] = (dataWarehouseSources?.results || []).map(
                    (source: ExternalDataSource): DataWarehouseDashboardDataSource => {
                        const sourceActivities = (recentActivity || []).filter(
                            (a) =>
                                !billingPeriodStart ||
                                !billingPeriodEnd ||
                                (dayjs(a.created_at).isAfter(billingPeriodStart.subtract(1, 'millisecond')) &&
                                    dayjs(a.created_at).isBefore(billingPeriodEnd))
                        )
                        const totalRows = totalRowsStats?.breakdown_of_rows_by_source?.[source.id] ?? 0
                        const sortedActivities = sourceActivities.sort(
                            (a, b) => dayjs(b.created_at).valueOf() - dayjs(a.created_at).valueOf()
                        )
                        const lastSync = sortedActivities.length > 0 ? sortedActivities[0].created_at : null
                        return {
                            id: source.id,
                            name: source.source_type,
                            status: source.status,
                            lastSync,
                            rowCount: totalRows,
                            url: urls.dataWarehouseSource(`managed-${source.id}`),
                        }
                    }
                )

                const selfManaged: DataWarehouseDashboardDataSource[] = (selfManagedTables || []).map((table) => ({
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
            (recentActivity: DataWarehouseActivityRecord[], activityCurrentPage: number) => {
                const pageSize = 5
                const totalData = recentActivity.length
                const pageCount = Math.ceil(totalData / pageSize)
                const startIndex = (activityCurrentPage - 1) * pageSize
                const endIndex = Math.min(startIndex + pageSize, totalData)
                const dataSourcePage = recentActivity.slice(startIndex, endIndex)

                return {
                    currentPage: activityCurrentPage,
                    pageCount,
                    dataSourcePage,
                    currentStartIndex: startIndex,
                    currentEndIndex: endIndex,
                    entryCount: totalData,
                    isOnLastPage: activityCurrentPage === pageCount,
                    hasDataOnCurrentPage: dataSourcePage.length > 0,
                }
            },
        ],
        materializedViews: [
            (s) => [s.views, s.dataWarehouseSavedQueryMapById],
            (views: any[], dataWarehouseSavedQueryMapById: any) => {
                return views
                    .filter((view: any) => dataWarehouseSavedQueryMapById[view.id]?.status)
                    .map((view: any) => ({
                        ...view,
                        type: 'materialized_view',
                        last_run_at: dataWarehouseSavedQueryMapById[view.id]?.last_run_at,
                        status: dataWarehouseSavedQueryMapById[view.id]?.status,
                    }))
            },
        ],
        tablesLoading: [
            (s) => [s.databaseLoading, s.dataWarehouseSourcesLoading],
            (databaseLoading: boolean, dataWarehouseSourcesLoading: boolean): boolean => {
                return databaseLoading || dataWarehouseSourcesLoading
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
    }),
    beforeUnmount(({ cache }) => {
        clearTimeout(cache.refreshTimeout)
    }),
])

export const dataWarehouseRowsSyncedGraphLogic = kea([
    path(['scenes', 'data-warehouse', 'dataWarehouseRowsSyncedGraphLogic']),
    actions({
        loadDailyBreakdown: true,
        setSelectedDate: (date) => ({ date }),
        setSelectedRows: (rows) => ({ rows }),
        clearModal: true,
    }),
    loaders(() => ({
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
        dailyRowsSyncedData: [
            (s: any) => [s.dailyBreakdownData],
            (dailyBreakdownData: DataWarehouseDailyRowsBreakdown | null): DailyRowsSyncedData[] => {
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
                let currentDate = billingStart

                while (currentDate.isSameOrBefore(billingEnd, 'day')) {
                    const isFutureDate = currentDate.isAfter(today, 'day')
                    dailyData.set(currentDate.format('YYYY-MM-DD'), isFutureDate ? null : 0)
                    currentDate = currentDate.add(1, 'day')
                }

                if (dailyBreakdownData.breakdown_of_rows_by_day) {
                    dailyBreakdownData.breakdown_of_rows_by_day.forEach(({ date, rows_synced }) => {
                        const dateObj = dayjs(date)
                        if (dateObj.isSameOrBefore(today, 'day')) {
                            dailyData.set(date, rows_synced)
                        }
                    })
                }

                return Array.from(dailyData.entries())
                    .map(([date, rows_synced]) => ({ date, rows_synced }))
                    .sort((a, b) => dayjs(a.date).unix() - dayjs(b.date).unix())
            },
        ],
        hasData: [
            (s: any) => [s.dailyRowsSyncedData],
            (dailyData: DailyRowsSyncedData[]): boolean =>
                dailyData.some((item) => item.rows_synced && item.rows_synced > 0),
        ],
        totalRowsInPeriod: [
            (s: any) => [s.dailyRowsSyncedData],
            (dailyData: DailyRowsSyncedData[]): number =>
                dailyData.reduce((sum, item) => sum + (item.rows_synced || 0), 0),
        ],
        selectedDateBreakdown: [
            (s: any) => [s.dailyBreakdownData, s.selectedDate],
            (dailyBreakdownData: DataWarehouseDailyRowsBreakdown | null, selectedDate: string | null) => {
                if (!dailyBreakdownData?.breakdown_of_rows_by_day || !selectedDate) {
                    return null
                }
                return (
                    dailyBreakdownData.breakdown_of_rows_by_day.find((breakdown) => breakdown.date === selectedDate) ||
                    null
                )
            },
        ],
        activitySummary: [
            (s: any) => [s.selectedDateBreakdown],
            (
                dateBreakdown: {
                    date: string
                    rows_synced: number
                    runs: Array<{
                        id: string
                        rows_synced: number
                        status: string
                        created_at: string
                        finished_at: string | null
                        schema_name: string
                        source_type: string
                        workflow_run_id: string
                    }>
                } | null
            ) => {
                if (!dateBreakdown) {
                    return null
                }

                const runs = dateBreakdown.runs || []
                const totalRowsProcessed = runs.reduce((sum, run) => sum + (run.rows_synced || 0), 0)
                const sortedRuns = runs.sort((a, b) => dayjs(b.created_at).valueOf() - dayjs(a.created_at).valueOf())

                const runsBySource = runs.reduce(
                    (acc, run) => {
                        const sourceName = run.source_type || 'Unknown'
                        if (!acc[sourceName]) {
                            acc[sourceName] = { count: 0, rows: 0, schemas: new Set<string>() }
                        }
                        acc[sourceName].count += 1
                        acc[sourceName].rows += run.rows_synced || 0
                        acc[sourceName].schemas.add(run.schema_name)
                        return acc
                    },
                    {} as Record<string, { count: number; rows: number; schemas: Set<string> }>
                )

                const statusCounts = runs.reduce(
                    (acc, run) => {
                        const status = run.status?.toLowerCase() || 'unknown'
                        acc[status] = (acc[status] || 0) + 1
                        return acc
                    },
                    {} as Record<string, number>
                )

                const avgRowsPerRun = runs.length > 0 ? Math.round(totalRowsProcessed / runs.length) : 0
                const timeSpan =
                    runs.length > 1
                        ? dayjs(sortedRuns[0].created_at).diff(
                              dayjs(sortedRuns[sortedRuns.length - 1].created_at),
                              'minute'
                          )
                        : 0

                return {
                    date: dateBreakdown.date,
                    totalRowsSynced: dateBreakdown.rows_synced,
                    totalRuns: runs.length,
                    totalRowsProcessed,
                    avgRowsPerRun,
                    timeSpanMinutes: timeSpan,
                    runsBySource: Object.fromEntries(
                        Object.entries(runsBySource).map(([source, data]) => [
                            source,
                            { ...data, schemas: Array.from(data.schemas) },
                        ])
                    ),
                    statusCounts,
                    runs: sortedRuns,
                    hasMultipleSources: Object.keys(runsBySource).length > 1,
                    mostActiveSource: Object.entries(runsBySource).sort((a, b) => b[1].rows - a[1].rows)[0]?.[0],
                    hasActivityData: runs.length > 0,
                    formattedDate: dayjs(dateBreakdown.date).format('MMM D, YYYY'),
                }
            },
        ],
        modalTitle: [
            (s: any) => [s.selectedDate],
            (selectedDate: string | null): string => {
                if (!selectedDate) {
                    return ''
                }
                return `Sync Activity - ${dayjs(selectedDate).format('MMM D, YYYY')}`
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDailyBreakdown()
    }),
])
