import { lemonToast } from '@posthog/lemon-ui'
import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { userLogic } from 'scenes/userLogic'

import { DatabaseSerializedFieldType } from '~/queries/schema'
import { DataWarehouseTable } from '~/types'

import { dataWarehouseSavedQueriesLogic } from '../saved_queries/dataWarehouseSavedQueriesLogic'
import {
    DatabaseTableListRow,
    DataWarehouseExternalTableType,
    DataWarehouseRowType,
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
            ['filteredTables', 'dataWarehouse', 'dataWarehouseLoading', 'databaseLoading'],
            dataWarehouseSavedQueriesLogic,
            ['savedQueries', 'dataWarehouseSavedQueriesLoading'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            dataWarehouseSavedQueriesLogic,
            [
                'loadDataWarehouseSavedQueries',
                'deleteDataWarehouseSavedQuery',
                'updateDataWarehouseSavedQuery',
                'updateDataWarehouseSavedQuerySuccess',
            ],
            databaseTableListLogic,
            [
                'loadDataWarehouse',
                'deleteDataWarehouseTable',
                'loadDataWarehouseSuccess',
                'loadDataWarehouseFailure',
                'loadDatabase',
                'loadDatabaseSuccess',
            ],
        ],
    })),
    actions(({ values }) => ({
        selectRow: (row: DataWarehouseTableType | null) => ({ row }),
        setIsEditingSavedQuery: (isEditingSavedQuery: boolean) => ({ isEditingSavedQuery }),
        toggleEditSchemaMode: (inEditSchemaMode?: boolean) => ({ inEditSchemaMode }),
        updateSelectedSchema: (columnKey: string, columnType: DatabaseSerializedFieldType) => ({
            columnKey,
            columnType,
        }),
        saveSchema: true,
        setEditSchemaIsLoading: (isLoading: boolean) => ({ isLoading }),
        cancelEditSchema: () => ({ dataWarehouse: values.dataWarehouse }),
    })),
    reducers({
        selectedRow: [
            null as DataWarehouseTableType | null,
            {
                selectRow: (_, { row }) => row,
                updateSelectedSchema: (state, { columnKey, columnType }) => {
                    if (!state) {
                        return state
                    }

                    const newState = { ...state }

                    const column = newState?.columns.find((n) => n.key === columnKey)
                    if (!column) {
                        return state
                    }

                    column.type = columnType
                    return newState
                },
                loadDataWarehouseSuccess: (state, { dataWarehouse }) => {
                    if (!state) {
                        return state
                    }

                    const table = dataWarehouse.results.find((n) => n.id === state.id)
                    if (!table) {
                        return state
                    }

                    return {
                        id: table.id,
                        name: table.name,
                        columns: table.columns,
                        payload: table,
                        type: DataWarehouseRowType.ExternalTable,
                    } as DataWarehouseTableType
                },
                loadDatabaseSuccess: (state, { database }) => {
                    if (!database || !state) {
                        return state
                    }

                    const columns = database[state.name]

                    if (columns) {
                        return {
                            id: state.name,
                            name: state.name,
                            columns: columns,
                            payload: { name: state.name, columns },
                            type: DataWarehouseRowType.PostHogTable,
                        }
                    }

                    return state
                },
                cancelEditSchema: (state, { dataWarehouse }) => {
                    if (!state || !dataWarehouse) {
                        return state
                    }

                    const table = dataWarehouse.results.find((n) => n.id === state.id)

                    if (!table) {
                        return state
                    }

                    return JSON.parse(
                        JSON.stringify({
                            id: table.id,
                            name: table.name,
                            columns: table.columns,
                            payload: table,
                            type: DataWarehouseRowType.ExternalTable,
                        })
                    )
                },
            },
        ],
        schemaUpdates: [
            {} as Record<string, DatabaseSerializedFieldType>,
            {
                updateSelectedSchema: (state, { columnKey, columnType }) => {
                    const newState = { ...state }

                    newState[columnKey] = columnType
                    return newState
                },
                toggleEditSchemaMode: () => ({}),
            },
        ],
        isEditingSavedQuery: [
            false,
            {
                setIsEditingSavedQuery: (_, { isEditingSavedQuery }) => isEditingSavedQuery,
            },
        ],
        inEditSchemaMode: [
            false as boolean,
            {
                toggleEditSchemaMode: (state, { inEditSchemaMode }) => {
                    if (inEditSchemaMode !== undefined) {
                        return inEditSchemaMode
                    }

                    return !state
                },
            },
        ],
        editSchemaIsLoading: [
            false as boolean,
            {
                setEditSchemaIsLoading: (_, { isLoading }) => isLoading,
                loadDataWarehouseSuccess: () => false,
                loadDataWarehouseFailure: () => false,
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

                const results = warehouse.results.map(
                    (table: DataWarehouseTable) =>
                        ({
                            id: table.id,
                            name: table.name,
                            columns: table.columns,
                            payload: table,
                            type: DataWarehouseRowType.ExternalTable,
                        } as DataWarehouseTableType)
                )

                // Deepcopy this so that edits dont modify the original objects
                return JSON.parse(JSON.stringify(results))
            },
        ],
        externalTablesMap: [
            (s) => [s.externalTables, s.savedQueriesFormatted],
            (externalTables, savedQueriesFormatted): Record<string, DataWarehouseTableType> => {
                return {
                    ...externalTables.reduce(
                        (acc: Record<string, DataWarehouseTableType>, table: DataWarehouseTableType) => {
                            acc[table.name] = table
                            return acc
                        },
                        {} as Record<string, DataWarehouseTableType>
                    ),
                    ...savedQueriesFormatted.reduce(
                        (acc: Record<string, DataWarehouseTableType>, table: DataWarehouseTableType) => {
                            acc[table.name] = table
                            return acc
                        },
                        {} as Record<string, DataWarehouseTableType>
                    ),
                }
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
        allTablesLoading: [
            (s) => [s.databaseLoading, s.dataWarehouseLoading],
            (databaseLoading, dataWarehouseLoading): boolean => {
                return databaseLoading || dataWarehouseLoading
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
    listeners(({ actions, values }) => ({
        deleteDataWarehouseSavedQuery: async (view) => {
            actions.selectRow(null)
            lemonToast.success(`${view.name} successfully deleted`)
        },
        deleteDataWarehouseTable: async (table) => {
            actions.selectRow(null)
            lemonToast.success(`${table.name} successfully deleted`)
        },
        selectRow: () => {
            actions.setIsEditingSavedQuery(false)
        },
        updateDataWarehouseSavedQuerySuccess: async ({ payload }) => {
            actions.setIsEditingSavedQuery(false)
            lemonToast.success(`${payload?.name ?? 'View'} successfully updated`)
        },
        saveSchema: async () => {
            const schemaUpdates = values.schemaUpdates
            const tableId = values.selectedRow?.id

            if (!tableId) {
                return
            }

            if (Object.keys(schemaUpdates).length === 0) {
                actions.toggleEditSchemaMode()
                return
            }

            actions.setEditSchemaIsLoading(true)

            try {
                await api.dataWarehouseTables.updateSchema(tableId, schemaUpdates)
                actions.loadDataWarehouse()
            } catch (e: any) {
                lemonToast.error(e.message)
                actions.setEditSchemaIsLoading(false)
            }
        },
        loadDataWarehouseSuccess: () => {
            if (values.inEditSchemaMode) {
                actions.toggleEditSchemaMode()
            }
        },
        loadDataWarehouseFailure: () => {
            if (values.inEditSchemaMode) {
                actions.toggleEditSchemaMode()
            }
        },
        cancelEditSchema: () => {
            actions.toggleEditSchemaMode(false)
        },
    })),
    afterMount(({ actions, values }) => {
        if (values.featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE]) {
            actions.loadDataWarehouse()
        }
    }),
])
