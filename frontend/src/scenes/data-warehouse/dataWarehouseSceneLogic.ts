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
    DataWarehouseDashboardDataSource,
    DataWarehouseSourceRowCount,
    ExternalDataSource,
} from '~/types'

import type { dataWarehouseSceneLogicType } from './dataWarehouseSceneLogicType'
import { externalDataSourcesLogic } from './externalDataSourcesLogic'
import { dataWarehouseViewsLogic } from './saved_queries/dataWarehouseViewsLogic'

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
                    .filter((view: any) => dataWarehouseSavedQueryMapById[view.id]?.is_materialized)
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
