import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api, { PaginatedResponse } from 'lib/api'
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
        startingMaterialization: [
            false,
            {
                setStartingMaterialization: (_, { starting }) => starting,
                loadDataModelingJobsSuccess: (state, { dataModelingJobs }) => {
                    const currentJobStatus = dataModelingJobs?.results?.[0]?.status
                    if (
                        currentJobStatus &&
                        ['Running', 'Completed', 'Failed', 'Cancelled'].includes(currentJobStatus)
                    ) {
                        return false
                    }
                    return state
                },
            },
        ],
    }),
    actions({
        runDataWarehouseSavedQuery: (viewId: string) => ({ viewId }),
        cancelDataWarehouseSavedQuery: (viewId: string) => ({ viewId }),
        revertMaterialization: (viewId: string) => ({ viewId }),
        loadOlderDataModelingJobs: () => {},
        resetDataModelingJobs: () => {},
        setStartingMaterialization: (starting: boolean) => ({ starting }),
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
                        edited_history_id?: string
                    }
                ) => {
                    const newView = await api.dataWarehouseSavedQueries.update(view.id, view)
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
                        values.dataModelingJobs?.results.length
                            ? Math.max(values.dataModelingJobs?.results.length, DEFAULT_JOBS_PAGE_SIZE)
                            : DEFAULT_JOBS_PAGE_SIZE,
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
        },
        updateDataWarehouseSavedQueryError: () => {
            lemonToast.error('Failed to update view')
        },
        runDataWarehouseSavedQuery: async ({ viewId }) => {
            try {
                await api.dataWarehouseSavedQueries.run(viewId)
                lemonToast.success('Materialization started')
                actions.loadDataWarehouseSavedQueries()
            } catch {
                lemonToast.error(`Failed to run materialization`)
            }
        },
        cancelDataWarehouseSavedQuery: async ({ viewId }) => {
            try {
                await api.dataWarehouseSavedQueries.cancel(viewId)
                lemonToast.success('Materialization cancelled')
                actions.loadDataWarehouseSavedQueries()
            } catch {
                lemonToast.error(`Failed to cancel materialization`)
            }
        },
        revertMaterialization: async ({ viewId }) => {
            try {
                await api.dataWarehouseSavedQueries.revertMaterialization(viewId)
                lemonToast.success('Materialization reverted')
                actions.loadDataWarehouseSavedQueries()
                actions.loadDatabase()
            } catch {
                lemonToast.error(`Failed to revert materialization`)
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
                    dataWarehouseSavedQueries?.reduce(
                        (acc, cur) => {
                            acc[cur.id] = cur
                            return acc
                        },
                        {} as Record<string, DataWarehouseSavedQuery>
                    ) ?? {}
                )
            },
        ],
        // id hyphens are removed. Used for hex'd id paths in DAG
        dataWarehouseSavedQueryMapByIdStringMap: [
            (s) => [s.dataWarehouseSavedQueries],
            (dataWarehouseSavedQueries) => {
                return (
                    dataWarehouseSavedQueries?.reduce(
                        (acc, cur) => {
                            acc[cur.id.replace(/-/g, '')] = cur
                            return acc
                        },
                        {} as Record<string, DataWarehouseSavedQuery>
                    ) ?? {}
                )
            },
        ],
        dataWarehouseSavedQueryMap: [
            (s) => [s.dataWarehouseSavedQueries],
            (dataWarehouseSavedQueries) => {
                return (
                    dataWarehouseSavedQueries?.reduce(
                        (acc, cur) => {
                            acc[cur.name] = cur
                            return acc
                        },
                        {} as Record<string, DataWarehouseSavedQuery>
                    ) ?? {}
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
