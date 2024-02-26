import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { userLogic } from 'scenes/userLogic'

import { DataWarehouseTable } from '~/types'

import { dataWarehouseSavedQueriesLogic } from '../saved_queries/dataWarehouseSavedQueriesLogic'
import { DatabaseTableListRow, DataWarehouseRowType, DataWarehouseTableType } from '../types'
import type { dataWarehouseSceneLogicType } from './dataWarehouseSceneLogicType'

export const dataWarehouseSceneLogic = kea<dataWarehouseSceneLogicType>([
    path(['scenes', 'warehouse', 'dataWarehouseSceneLogic']),
    connect(() => ({
        values: [
            userLogic,
            ['user'],
            databaseTableListLogic,
            ['filteredTables'],
            dataWarehouseSavedQueriesLogic,
            ['savedQueries'],
        ],
        actions: [dataWarehouseSavedQueriesLogic, ['deleteDataWarehouseSavedQuery']],
    })),
    actions({
        toggleSourceModal: (isOpen?: boolean) => ({ isOpen }),
        selectRow: (row: DataWarehouseTableType | null) => ({ row }),
    }),
    reducers({
        isSourceModalOpen: [
            false,
            {
                toggleSourceModal: (state, { isOpen }) => (isOpen != undefined ? isOpen : !state),
            },
        ],
        selectedRow: [
            null as DataWarehouseTableType | null,
            {
                selectRow: (_, { row }) => row,
            },
        ],
    }),
    loaders(({ values }) => ({
        dataWarehouse: [
            null as PaginatedResponse<DataWarehouseTable> | null,
            {
                loadDataWarehouse: async (): Promise<PaginatedResponse<DataWarehouseTable>> =>
                    await api.dataWarehouseTables.list(),
                deleteDataWarehouseTable: async (table: DataWarehouseTable) => {
                    await api.dataWarehouseTables.delete(table.id)
                    return {
                        results: [...(values.dataWarehouse?.results || []).filter((t) => t.id != table.id)],
                    }
                },
            },
        ],
    })),
    selectors({
        externalTables: [
            (s) => [s.dataWarehouse],
            (warehouse): DataWarehouseTableType[] => {
                if (!warehouse) {
                    return []
                }

                return warehouse.results.map(
                    (table: DataWarehouseTable) =>
                        ({
                            id: table.id,
                            name: table.name,
                            columns: table.columns,
                            payload: table,
                            type: DataWarehouseRowType.ExternalTable,
                        } as DataWarehouseTableType)
                )
            },
        ],
        externalTablesMap: [
            (s) => [s.externalTables],
            (externalTables): Record<string, DataWarehouseTableType> => {
                return externalTables.reduce(
                    (acc: Record<string, DataWarehouseTableType>, table: DataWarehouseTableType) => {
                        acc[table.name] = table
                        return acc
                    },
                    {} as Record<string, DataWarehouseTableType>
                )
            },
        ],
        posthogTables: [
            (s) => [s.filteredTables],
            (tables): DataWarehouseTableType[] => {
                if (!tables) {
                    return []
                }

                return tables.map(
                    (table: DatabaseTableListRow) =>
                        ({
                            id: table.name,
                            name: table.name,
                            columns: table.columns,
                            payload: table,
                            type: DataWarehouseRowType.PostHogTable,
                        } as DataWarehouseTableType)
                )
            },
        ],
        savedQueriesFormatted: [
            (s) => [s.savedQueries],
            (savedQueries): DataWarehouseTableType[] => {
                if (!savedQueries) {
                    return []
                }

                return savedQueries.map(
                    (query) =>
                        ({
                            id: query.id,
                            name: query.name,
                            columns: query.columns,
                            type: DataWarehouseRowType.View,
                            payload: query,
                        } as DataWarehouseTableType)
                )
            },
        ],
        allTables: [
            (s) => [s.externalTables, s.posthogTables, s.savedQueriesFormatted],
            (externalTables, posthogTables, savedQueriesFormatted): DataWarehouseTableType[] => {
                return [...externalTables, ...posthogTables, ...savedQueriesFormatted]
            },
        ],
    }),
    listeners(({ actions }) => ({
        deleteDataWarehouseSavedQuery: async (view) => {
            actions.selectRow(null)
            lemonToast.success(`${view.name} successfully deleted`)
        },
        deleteDataWarehouseTable: async (table) => {
            actions.selectRow(null)
            lemonToast.success(`${table.name} successfully deleted`)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadDataWarehouse()
    }),
])
