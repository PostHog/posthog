import { actions, connect, events, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SetupTaskId, globalSetupLogic } from 'lib/components/ProductSetup'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { userLogic } from 'scenes/userLogic'

import { DatabaseSchemaViewTable } from '~/queries/schema/schema-general'
import { DataWarehouseSavedQuery } from '~/types'

import type { dataWarehouseViewsLogicType } from './dataWarehouseViewsLogicType'

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
        cancelDataWarehouseSavedQuery: (viewId: string) => ({ viewId }),
        materializeDataWarehouseSavedQuery: (viewId: string) => ({ viewId }),
        revertMaterialization: (viewId: string) => ({ viewId }),
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
                    globalSetupLogic.findMounted()?.actions.markTaskAsCompleted(SetupTaskId.CreateSavedView)

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
    })),
    listeners(({ actions }) => ({
        createDataWarehouseSavedQuerySuccess: () => {
            actions.loadDatabase()
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

            // Toast is handled by dataWarehouseSettingsSceneLogic when needed
        },
        updateDataWarehouseSavedQueryError: () => {
            lemonToast.error('Failed to update view')
        },
        deleteDataWarehouseSavedQuerySuccess: () => {
            lemonToast.success('View deleted')
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
        materializeDataWarehouseSavedQuery: async ({ viewId }) => {
            try {
                await api.dataWarehouseSavedQueries.materialize(viewId)
                lemonToast.success('View materialized successfully')
                posthog.capture('materialized view created', {
                    sync_frequency: '24hour',
                })
                actions.loadDataWarehouseSavedQueries()
                actions.loadDatabase()
            } catch {
                lemonToast.error(`Failed to materialize view`)
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
    }),
    events(({ actions }) => ({
        afterMount: () => {
            actions.loadDataWarehouseSavedQueries()
        },
    })),
])
