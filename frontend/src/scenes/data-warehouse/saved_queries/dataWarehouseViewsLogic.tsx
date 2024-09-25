import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, events, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { DatabaseSchemaViewTable } from '~/queries/schema'
import { DataWarehouseSavedQuery } from '~/types'

import type { dataWarehouseViewsLogicType } from './dataWarehouseViewsLogicType'

export const dataWarehouseViewsLogic = kea<dataWarehouseViewsLogicType>([
    path(['scenes', 'warehouse', 'dataWarehouseSavedQueriesLogic']),
    connect(() => ({
        values: [userLogic, ['user'], databaseTableListLogic, ['views', 'databaseLoading']],
        actions: [databaseTableListLogic, ['loadDatabase']],
    })),
    actions({
        runDataWarehouseSavedQuery: (viewId: string) => ({ viewId }),
    }),
    loaders(({ values }) => ({
        dataWarehouseSavedQueries: [
            [] as DataWarehouseSavedQuery[],
            {
                loadDataWarehouseSavedQueries: async () => {
                    const savedQueries = await api.dataWarehouseSavedQueries.list()
                    return savedQueries.results
                },
                createDataWarehouseSavedQuery: async (view: Partial<DatabaseSchemaViewTable>) => {
                    const newView = await api.dataWarehouseSavedQueries.create(view)

                    lemonToast.success(`${newView.name ?? 'View'} successfully created`)
                    router.actions.push(urls.dataWarehouseView(newView.id))

                    return [...values.dataWarehouseSavedQueries, newView]
                },
                deleteDataWarehouseSavedQuery: async (viewId: string) => {
                    await api.dataWarehouseSavedQueries.delete(viewId)
                    return values.dataWarehouseSavedQueries.filter((view) => view.id !== viewId)
                },
                updateDataWarehouseSavedQuery: async (view: DatabaseSchemaViewTable) => {
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
        updateDataWarehouseSavedQuerySuccess: () => {
            actions.loadDatabase()
        },
        runDataWarehouseSavedQuery: async ({ viewId }) => {
            await api.dataWarehouseSavedQueries.run(viewId)
            actions.loadDataWarehouseSavedQueries()
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
    }),
    events(({ actions, cache }) => ({
        afterMount: () => {
            actions.loadDataWarehouseSavedQueries()
            if (!cache.pollingInterval) {
                cache.pollingInterval = setInterval(() => {
                    actions.loadDataWarehouseSavedQueries()
                }, 5000)
            }
        },
        beforeUnmount: () => {
            clearInterval(cache.pollingInterval)
        },
    })),
])
