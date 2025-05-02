import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import posthog from 'posthog-js'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { userLogic } from 'scenes/userLogic'

import { DatabaseSchemaViewTable } from '~/queries/schema/schema-general'
import { DataModelingJob, DataWarehouseSavedQuery } from '~/types'

import type { dataWarehouseViewsLogicType } from './dataWarehouseViewsLogicType'

const REFRESH_INTERVAL = 10000
const DEFAULT_JOBS_PAGE_SIZE = 10

export const dataWarehouseViewsLogic = kea<dataWarehouseViewsLogicType>([
    path(['scenes', 'warehouse', 'dataWarehouseSavedQueriesLogic']),
    connect(() => ({
        values: [userLogic, ['user'], databaseTableListLogic, ['views', 'databaseLoading']],
        actions: [databaseTableListLogic, ['loadDatabase']],
    })),
    reducers({
        initialDataWarehouseSavedQueryLoading: [
            true,
            {
                loadDataWarehouseSavedQueriesSuccess: () => false,
                loadDataWarehouseSavedQueriesFailure: () => false,
            },
        ],
        updatingDataWarehouseSavedQuery: [
            false,
            {
                updateDataWarehouseSavedQuery: () => true,
                updateDataWarehouseSavedQuerySuccess: () => false,
                updateDataWarehouseSavedQueryFailure: () => false,
            },
        ],
    }),
    actions({
        runDataWarehouseSavedQuery: (viewId: string) => ({ viewId }),
        loadOlderDataModelingJobs: () => {},
        resetDataModelingJobs: () => {},
    }),
    loaders(({ values }) => ({
        dataWarehouseSavedQueries: [
            [] as DataWarehouseSavedQuery[],
            {
                loadDataWarehouseSavedQueries: async () => {
                    const savedQueries = await api.dataWarehouseSavedQueries.list()
                    return savedQueries.results
                },
                createDataWarehouseSavedQuery: async (
                    view: Partial<DatabaseSchemaViewTable> & { types: string[][] }
                ) => {
                    const newView = await api.dataWarehouseSavedQueries.create(view)

                    lemonToast.success(`${newView.name ?? 'View'} successfully created`)

                    return [...values.dataWarehouseSavedQueries, newView]
                },
                deleteDataWarehouseSavedQuery: async (viewId: string) => {
                    await api.dataWarehouseSavedQueries.delete(viewId)
                    return values.dataWarehouseSavedQueries.filter((view) => view.id !== viewId)
                },
                updateDataWarehouseSavedQuery: async (
                    view: Partial<DatabaseSchemaViewTable> & {
                        id: string
                        types: string[][]
                        sync_frequency?: string
                        lifecycle?: string
                        shouldRematerialize?: boolean
                    }
                ) => {
                    const current_query = values.dataWarehouseSavedQueryMapById[view.id]?.query
                    const newView = await api.dataWarehouseSavedQueries.update(view.id, {
                        ...view,
                        current_query: current_query?.query,
                    })
                    return values.dataWarehouseSavedQueries.map((savedQuery) => {
                        if (savedQuery.id === view.id) {
                            return newView
                        }
                        return savedQuery
                    })
                },
            },
        ],
        dataModelingJobs: [
            null as PaginatedResponse<DataModelingJob> | null,
            {
                loadDataModelingJobs: async (savedQueryId: string) => {
                    return await api.dataWarehouseSavedQueries.dataWarehouseDataModelingJobs.list(
                        savedQueryId,
                        values.dataModelingJobs?.results.length ?? DEFAULT_JOBS_PAGE_SIZE,
                        0
                    )
                },
                loadOlderDataModelingJobs: async () => {
                    const nextUrl = values.dataModelingJobs?.next

                    if (!nextUrl) {
                        return values.dataModelingJobs
                    }

                    const res = await api.get<PaginatedResponse<DataModelingJob>>(nextUrl)
                    res.results = [...(values.dataModelingJobs?.results ?? []), ...res.results]

                    return res
                },
                resetDataModelingJobs: () => null,
            },
        ],
    })),
    listeners(({ actions, cache }) => ({
        createDataWarehouseSavedQuerySuccess: () => {
            actions.loadDatabase()
        },
        loadDataWarehouseSavedQueriesSuccess: () => {
            clearTimeout(cache.savedQueriesRefreshTimeout)

            cache.savedQueriesRefreshTimeout = setTimeout(() => {
                actions.loadDataWarehouseSavedQueries()
            }, REFRESH_INTERVAL)
        },
        loadDataModelingJobsSuccess: ({ payload }) => {
            clearTimeout(cache.dataModelingJobsRefreshTimeout)

            cache.dataModelingJobsRefreshTimeout = setTimeout(() => {
                if (payload) {
                    actions.loadDataModelingJobs(payload)
                }
            }, REFRESH_INTERVAL)
        },
        updateDataWarehouseSavedQuerySuccess: ({ payload }) => {
            // in the case where we are scheduling a materialized view, send an event
            if (payload && payload.lifecycle && payload.sync_frequency) {
                // this function exists as an upsert, so we need to check if the view was created or updated
                posthog.capture(`materialized view ${payload.lifecycle === 'update' ? 'updated' : 'created'}`, {
                    sync_frequency: payload.sync_frequency,
                })
            }

            if (payload?.shouldRematerialize) {
                actions.runDataWarehouseSavedQuery(payload.id)
            }

            actions.loadDatabase()
            lemonToast.success('View updated')
        },
        updateDataWarehouseSavedQueryError: () => {
            lemonToast.error('Failed to update view')
        },
        runDataWarehouseSavedQuery: async ({ viewId }) => {
            try {
                await api.dataWarehouseSavedQueries.run(viewId)
                lemonToast.success('Materialization started')
                actions.loadDataWarehouseSavedQueries()
            } catch (error) {
                lemonToast.error(`Failed to run materialization`)
            }
        },
    })),
    selectors({
        shouldShowEmptyState: [
            (s) => [s.views, s.databaseLoading],
            (views, databaseLoading): boolean => {
                return views?.length == 0 && !databaseLoading
            },
        ],
        dataWarehouseSavedQueryMapById: [
            (s) => [s.dataWarehouseSavedQueries],
            (dataWarehouseSavedQueries) => {
                return (
                    dataWarehouseSavedQueries?.reduce((acc, cur) => {
                        acc[cur.id] = cur
                        return acc
                    }, {} as Record<string, DataWarehouseSavedQuery>) ?? {}
                )
            },
        ],
        dataWarehouseSavedQueryMap: [
            (s) => [s.dataWarehouseSavedQueries],
            (dataWarehouseSavedQueries) => {
                return (
                    dataWarehouseSavedQueries?.reduce((acc, cur) => {
                        acc[cur.name] = cur
                        return acc
                    }, {} as Record<string, DataWarehouseSavedQuery>) ?? {}
                )
            },
        ],
        hasMoreJobsToLoad: [(s) => [s.dataModelingJobs], (dataModelingJobs) => !!dataModelingJobs?.next],
    }),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadDataWarehouseSavedQueries()
        },
        beforeUnmount: () => {
            clearTimeout(cache.savedQueriesRefreshTimeout)
        },
    })),
])
