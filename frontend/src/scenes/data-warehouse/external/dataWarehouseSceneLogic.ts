import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { userLogic } from 'scenes/userLogic'

import { DataWarehouseTable } from '~/types'

import { dataWarehouseSavedQueriesLogic } from '../saved_queries/dataWarehouseSavedQueriesLogic'
import {
    DatabaseTableListRow,
    DataWarehouseExternalTableType,
    DataWarehouseRowType,
    DataWarehouseSceneTab,
    DataWarehouseTableType,
} from '../types'
import type { dataWarehouseSceneLogicType } from './dataWarehouseSceneLogicType'

export const dataWarehouseSceneLogic = kea<dataWarehouseSceneLogicType>([
    path(['scenes', 'warehouse', 'dataWarehouseSceneLogic']),
    connect(() => ({
        values: [
            userLogic,
            ['user'],
            databaseTableListLogic,
            ['filteredTables', 'dataWarehouse', 'dataWarehouseLoading'],
            dataWarehouseSavedQueriesLogic,
            ['savedQueries', 'dataWarehouseSavedQueriesLoading'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            dataWarehouseSavedQueriesLogic,
            ['deleteDataWarehouseSavedQuery'],
            databaseTableListLogic,
            ['loadDataWarehouse', 'deleteDataWarehouseTable'],
        ],
    })),
    actions({
        toggleSourceModal: (isOpen?: boolean) => ({ isOpen }),
        selectRow: (row: DataWarehouseTableType | null) => ({ row }),
        setSceneTab: (tab: DataWarehouseSceneTab) => ({ tab }),
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
        activeSceneTab: [
            DataWarehouseSceneTab.Tables as DataWarehouseSceneTab,
            {
                setSceneTab: (_state, { tab }) => tab,
            },
        ],
    }),
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
        externalTablesBySourceType: [
            (s) => [s.externalTables],
            (externalTables): Record<string, DataWarehouseTableType[]> => {
                return externalTables.reduce((acc: Record<string, DataWarehouseTableType[]>, table) => {
                    table = table as DataWarehouseExternalTableType
                    if (table.payload.external_data_source) {
                        if (!acc[table.payload.external_data_source.source_type]) {
                            acc[table.payload.external_data_source.source_type] = []
                        }
                        acc[table.payload.external_data_source.source_type].push(table)
                    } else {
                        if (!acc['S3']) {
                            acc['S3'] = []
                        }
                        acc['S3'].push(table)
                    }
                    return acc
                }, {})
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
    afterMount(({ actions, values }) => {
        if (values.featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE]) {
            actions.loadDataWarehouse()
        }
    }),
])
