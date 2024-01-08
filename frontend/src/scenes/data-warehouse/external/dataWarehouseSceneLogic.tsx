import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { userLogic } from 'scenes/userLogic'

import { DataWarehouseTable } from '~/types'

import { dataWarehouseSavedQueriesLogic } from '../saved_queries/dataWarehouseSavedQueriesLogic'
import { DatabaseTableListRow, DataWarehouseRowType, DataWarehouseSceneRow } from '../types'
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
        selectRow: (row: DataWarehouseSceneRow | null) => ({ row }),
        deleteView: (view: DataWarehouseSceneRow) => ({ view }),
    }),
    reducers({
        isSourceModalOpen: [
            false,
            {
                toggleSourceModal: (state, { isOpen }) => (isOpen != undefined ? isOpen : !state),
            },
        ],
        selectedRow: [
            null as DataWarehouseSceneRow | null,
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
            (warehouse): DataWarehouseSceneRow[] => {
                if (!warehouse) {
                    return []
                }

                return warehouse.results.map(
                    (table: DataWarehouseTable) =>
                        ({
                            id: table.id,
                            name: table.name,
                            columns: table.columns,
                            url_pattern: table.url_pattern,
                            format: table.format,
                            external_data_source: table.external_data_source,
                            external_schema: table.external_schema,
                            type: DataWarehouseRowType.ExternalTable,
                        } as DataWarehouseSceneRow)
                )
            },
        ],
        posthogTables: [
            (s) => [s.filteredTables],
            (tables): DataWarehouseSceneRow[] => {
                if (!tables) {
                    return []
                }

                return tables.map(
                    (table: DatabaseTableListRow) =>
                        ({
                            name: table.name,
                            columns: table.columns,
                            type: DataWarehouseRowType.PostHogTable,
                        } as DataWarehouseSceneRow)
                )
            },
        ],
        savedQueriesFormatted: [
            (s) => [s.savedQueries],
            (savedQueries): DataWarehouseSceneRow[] => {
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
                            query: query.query,
                        } as DataWarehouseSceneRow)
                )
            },
        ],
        allTables: [
            (s) => [s.externalTables, s.posthogTables, s.savedQueriesFormatted],
            (externalTables, posthogTables, savedQueriesFormatted): DataWarehouseSceneRow[] => {
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
