import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api, { PaginatedResponse } from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { userLogic } from 'scenes/userLogic'

import { DataWarehouseTable, ProductKey } from '~/types'

import { DatabaseTableListRow, DataWarehouseSceneRow } from '../types'
import type { dataWarehouseSceneLogicType } from './dataWarehouseSceneLogicType'

export const dataWarehouseSceneLogic = kea<dataWarehouseSceneLogicType>([
    path(['scenes', 'warehouse', 'dataWarehouseSceneLogic']),
    connect(() => ({
        values: [userLogic, ['user'], databaseTableListLogic, ['filteredTables']],
    })),
    actions({
        toggleSourceModal: (isOpen?: boolean) => ({ isOpen }),
    }),
    reducers({
        isSourceModalOpen: [
            false,
            {
                toggleSourceModal: (state, { isOpen }) => (isOpen != undefined ? isOpen : !state),
            },
        ],
    }),
    loaders({
        dataWarehouse: [
            null as PaginatedResponse<DataWarehouseTable> | null,
            {
                loadDataWarehouse: async (): Promise<PaginatedResponse<DataWarehouseTable>> =>
                    await api.dataWarehouseTables.list(),
            },
        ],
    }),
    selectors({
        tables: [
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
                        } as DataWarehouseSceneRow)
                )
            },
        ],
        shouldShowEmptyState: [
            (s) => [s.tables, s.dataWarehouseLoading],
            (tables, dataWarehouseLoading): boolean => {
                return tables?.length == 0 && !dataWarehouseLoading
            },
        ],
        shouldShowProductIntroduction: [
            (s) => [s.user],
            (user): boolean => {
                return !user?.has_seen_product_intro_for?.[ProductKey.DATA_WAREHOUSE]
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadDataWarehouse()
    }),
])
