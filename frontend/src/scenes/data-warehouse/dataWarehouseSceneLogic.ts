import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import posthog from 'posthog-js'

import api, { PaginatedResponse } from 'lib/api'
import { billingLogic } from 'scenes/billing/billingLogic'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { DatabaseSchemaDataWarehouseTable } from '~/queries/schema/schema-general'
import {
    BillingProductV2Type,
    DataWarehouseActivityRecord,
    DataWarehouseJobStats,
    DataWarehouseJobStatsRequestPayload,
    DataWarehouseSourceRowCount,
} from '~/types'

import type { dataWarehouseSceneLogicType } from './dataWarehouseSceneLogicType'
import { externalDataSourcesLogic } from './externalDataSourcesLogic'
import { dataWarehouseViewsLogic } from './saved_queries/dataWarehouseViewsLogic'

const REFRESH_INTERVAL = 10000

export enum DataWarehouseTab {
    OVERVIEW = 'overview',
    SOURCES = 'sources',
}

export const dataWarehouseSceneLogic = kea<dataWarehouseSceneLogicType>([
    path(['scenes', 'data-warehouse', 'dataWarehouseSceneLogic']),
    connect(() => ({
        values: [
            databaseTableListLogic,
            ['dataWarehouseTables', 'views', 'databaseLoading'],
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
            billingLogic,
            ['loadBilling'],
        ],
    })),
    actions({
        loadMoreRunningActivity: true,
        loadMoreCompletedActivity: true,
        setActivityRunningCurrentPage: (page: number) => ({ page }),
        setActivityCompletedCurrentPage: (page: number) => ({ page }),
        checkAutoLoadMoreRunning: true,
        checkAutoLoadMoreCompleted: true,
        setActiveTab: (tab: DataWarehouseTab) => ({ tab }),
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
        runningActivityResponse: [
            null as PaginatedResponse<DataWarehouseActivityRecord> | null,
            {
                loadRunningActivityResponse: async () => {
                    return await api.dataWarehouse.runningActivity({ limit: 20, offset: 0, cutoff_days: 30 })
                },
            },
        ],
        completedActivityResponse: [
            null as PaginatedResponse<DataWarehouseActivityRecord> | null,
            {
                loadCompletedActivityResponse: async () => {
                    return await api.dataWarehouse.completedActivity({ limit: 20, offset: 0, cutoff_days: 30 })
                },
            },
        ],
        jobStats: [
            null as DataWarehouseJobStats | null,
            {
                loadJobStats: async ({ days }: DataWarehouseJobStatsRequestPayload) => {
                    return await api.dataWarehouse.jobStats({ days })
                },
            },
        ],
    })),
    reducers(() => ({
        activeTab: [
            DataWarehouseTab.OVERVIEW as DataWarehouseTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        activityRunningCurrentPage: [
            1 as number,
            {
                setActivityRunningCurrentPage: (_, { page }) => page,
                loadRunningActivityResponse: () => 1,
            },
        ],
        activityCompletedCurrentPage: [
            1 as number,
            {
                setActivityCompletedCurrentPage: (_, { page }) => page,
                loadCompletedActivityResponse: () => 1,
            },
        ],
        runningActivityMoreLoading: [
            false as boolean,
            {
                loadMoreRunningActivity: () => true,
                loadRunningActivityResponseSuccess: () => false,
            },
        ],
        completedActivityMoreLoading: [
            false as boolean,
            {
                loadMoreCompletedActivity: () => true,
                loadCompletedActivityResponseSuccess: () => false,
            },
        ],
    })),
    selectors({
        recentActivityRunning: [
            (s) => [s.runningActivityResponse],
            (response: PaginatedResponse<DataWarehouseActivityRecord> | null): DataWarehouseActivityRecord[] => {
                return response?.results || []
            },
        ],
        recentActivityCompleted: [
            (s) => [s.completedActivityResponse],
            (response: PaginatedResponse<DataWarehouseActivityRecord> | null): DataWarehouseActivityRecord[] => {
                return response?.results || []
            },
        ],
        recentActivityRunningHasMore: [
            (s) => [s.runningActivityResponse],
            (response: PaginatedResponse<DataWarehouseActivityRecord> | null): boolean => {
                return !!response?.next
            },
        ],
        recentActivityCompletedHasMore: [
            (s) => [s.completedActivityResponse],
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
        activityRunningPaginationState: [
            (s) => [s.recentActivityRunning, s.activityRunningCurrentPage],
            (recentActivityRunning: DataWarehouseActivityRecord[], activityRunningCurrentPage: number) => {
                const pageSize = 8
                const totalData = recentActivityRunning.length
                const pageCount = Math.max(Math.ceil(totalData / pageSize), 1)
                const startIndex = (activityRunningCurrentPage - 1) * pageSize
                const endIndex = Math.min(startIndex + pageSize, totalData)
                const dataSourcePage = recentActivityRunning.slice(startIndex, endIndex)

                return {
                    currentPage: activityRunningCurrentPage,
                    pageCount,
                    dataSourcePage,
                    currentStartIndex: startIndex,
                    currentEndIndex: endIndex,
                    entryCount: totalData,
                    isOnLastPage: activityRunningCurrentPage === pageCount,
                    hasDataOnCurrentPage: dataSourcePage.length > 0,
                }
            },
        ],
        activityCompletedPaginationState: [
            (s) => [s.recentActivityCompleted, s.activityCompletedCurrentPage],
            (recentActivityCompleted: DataWarehouseActivityRecord[], activityCompletedCurrentPage: number) => {
                const pageSize = 8
                const totalData = recentActivityCompleted.length
                const pageCount = Math.max(Math.ceil(totalData / pageSize), 1)
                const startIndex = (activityCompletedCurrentPage - 1) * pageSize
                const endIndex = Math.min(startIndex + pageSize, totalData)
                const dataSourcePage = recentActivityCompleted.slice(startIndex, endIndex)

                return {
                    currentPage: activityCompletedCurrentPage,
                    pageCount,
                    dataSourcePage,
                    currentStartIndex: startIndex,
                    currentEndIndex: endIndex,
                    entryCount: totalData,
                    isOnLastPage: activityCompletedCurrentPage === pageCount,
                    hasDataOnCurrentPage: dataSourcePage.length > 0,
                }
            },
        ],
        tablesLoading: [
            (s) => [s.databaseLoading, s.dataWarehouseSourcesLoading],
            (databaseLoading: boolean, dataWarehouseSourcesLoading: boolean): boolean => {
                return databaseLoading || dataWarehouseSourcesLoading
            },
        ],
        materializedViews: [
            (s) => [s.views, s.dataWarehouseSavedQueryMapById],
            (views, dataWarehouseSavedQueryMapById) => {
                return views.filter((view) => dataWarehouseSavedQueryMapById[view.id]?.is_materialized)
            },
        ],
        dataWarehouseProduct: [
            (s) => [s.billing],
            (billing): BillingProductV2Type | null => {
                return billing?.products?.find((product) => product.type === 'data_warehouse') || null
            },
        ],
    }),
    listeners(({ values, actions, cache }) => ({
        setActivityRunningCurrentPage: () => {
            actions.checkAutoLoadMoreRunning()
        },
        setActivityCompletedCurrentPage: () => {
            actions.checkAutoLoadMoreCompleted()
        },
        checkAutoLoadMoreRunning: () => {
            const paginationState = values.activityRunningPaginationState
            const { isOnLastPage, hasDataOnCurrentPage } = paginationState
            const { recentActivityRunningHasMore, runningActivityResponseLoading } = values

            if (
                isOnLastPage &&
                hasDataOnCurrentPage &&
                recentActivityRunningHasMore &&
                !runningActivityResponseLoading
            ) {
                actions.loadMoreRunningActivity()
            }
        },
        checkAutoLoadMoreCompleted: () => {
            const paginationState = values.activityCompletedPaginationState
            const { isOnLastPage, hasDataOnCurrentPage } = paginationState
            const { recentActivityCompletedHasMore, completedActivityResponseLoading } = values

            if (
                isOnLastPage &&
                hasDataOnCurrentPage &&
                recentActivityCompletedHasMore &&
                !completedActivityResponseLoading
            ) {
                actions.loadMoreCompletedActivity()
            }
        },
        loadMoreRunningActivity: async () => {
            try {
                const currentData = values.recentActivityRunning
                const response = await api.dataWarehouse.runningActivity({
                    limit: 20,
                    offset: currentData.length,
                    cutoff_days: 30,
                })
                const newData = [...currentData, ...(response.results || [])]
                const newResponse = { ...response, results: newData }

                actions.loadRunningActivityResponseSuccess(newResponse)
            } catch (error) {
                posthog.captureException(error)
            }
        },
        loadMoreCompletedActivity: async () => {
            try {
                const currentData = values.recentActivityCompleted
                const response = await api.dataWarehouse.completedActivity({
                    limit: 20,
                    offset: currentData.length,
                    cutoff_days: 30,
                })
                const newData = [...currentData, ...(response.results || [])]
                const newResponse = { ...response, results: newData }

                actions.loadCompletedActivityResponseSuccess(newResponse)
            } catch (error) {
                posthog.captureException(error)
            }
        },
        loadSourcesSuccess: () => {
            // Remove any existing refresh timeout
            cache.disposables.dispose('refreshTimeout')

            if (router.values.location.pathname.includes('data-warehouse')) {
                cache.disposables.add(() => {
                    const timerId = setTimeout(() => {
                        actions.loadSources(null)
                    }, REFRESH_INTERVAL)
                    return () => clearTimeout(timerId)
                }, 'refreshTimeout')
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadSources(null)
        actions.loadRunningActivityResponse()
        actions.loadCompletedActivityResponse()
        actions.loadTotalRowsStats()
        actions.loadJobStats({ days: 7 })
        actions.loadBilling()
    }),
])
