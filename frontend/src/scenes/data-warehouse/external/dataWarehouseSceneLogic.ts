import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import api from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { DatabaseSchemaTable, DatabaseSerializedFieldType } from '~/queries/schema'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import { DataWarehouseSceneTab } from '../types'
import type { dataWarehouseSceneLogicType } from './dataWarehouseSceneLogicType'

export const dataWarehouseSceneLogic = kea<dataWarehouseSceneLogicType>([
    path(['scenes', 'warehouse', 'dataWarehouseSceneLogic']),
    connect(() => ({
        values: [
            databaseTableListLogic,
            ['database', 'posthogTables', 'dataWarehouseTables', 'databaseLoading', 'views'],
        ],
        actions: [
            dataWarehouseViewsLogic,
            ['deleteDataWarehouseSavedQuery', 'updateDataWarehouseSavedQuery', 'updateDataWarehouseSavedQuerySuccess'],
            databaseTableListLogic,
            ['loadDatabase', 'loadDatabaseSuccess', 'loadDatabaseFailure'],
        ],
    })),
    actions(({ values }) => ({
        selectRow: (row: DatabaseSchemaTable | null) => ({ row }),
        setSceneTab: (tab: DataWarehouseSceneTab) => ({ tab }),
        setIsEditingSavedQuery: (isEditingSavedQuery: boolean) => ({ isEditingSavedQuery }),
        toggleEditSchemaMode: (inEditSchemaMode?: boolean) => ({ inEditSchemaMode }),
        updateSelectedSchema: (columnKey: string, columnType: DatabaseSerializedFieldType) => ({
            columnKey,
            columnType,
        }),
        saveSchema: true,
        setEditSchemaIsLoading: (isLoading: boolean) => ({ isLoading }),
        cancelEditSchema: () => ({ database: values.database }),
        deleteDataWarehouseTable: (tableId: string) => ({ tableId }),
    })),
    reducers({
        selectedRow: [
            null as DatabaseSchemaTable | null,
            {
                selectRow: (_, { row }) => row,
                updateSelectedSchema: (state, { columnKey, columnType }) => {
                    if (!state) {
                        return state
                    }

                    const newState = { ...state }

                    const column = newState?.fields[columnKey]
                    if (!column) {
                        return state
                    }

                    column.type = columnType
                    return newState
                },
                loadDatabaseSuccess: (state, { database }) => {
                    if (!state || !database) {
                        return state
                    }

                    const table = Object.values(database.tables).find((n) => n.id === state.id)
                    if (!table) {
                        return state
                    }

                    return table
                },
                cancelEditSchema: (state, { database }) => {
                    if (!state || !database) {
                        return state
                    }

                    const table = Object.values(database.tables).find((n) => n.id === state.id)

                    if (!table) {
                        return state
                    }

                    return JSON.parse(JSON.stringify(table))
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
                loadDatabaseSuccess: () => false,
                loadDatabaseFailure: () => false,
            },
        ],
    }),
    selectors({
        dataWarehouseTablesBySourceType: [
            (s) => [s.dataWarehouseTables],
            (dataWarehouseTables): Record<string, DatabaseSchemaTable[]> => {
                return dataWarehouseTables.reduce((acc: Record<string, DatabaseSchemaTable[]>, table) => {
                    if (table.source) {
                        if (!acc[table.source.source_type]) {
                            acc[table.source.source_type] = []
                        }
                        acc[table.source.source_type].push(table)
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
        deleteDataWarehouseSavedQuery: async (tableId) => {
            await api.dataWarehouseSavedQueries.delete(tableId)
            actions.selectRow(null)
            actions.loadDatabase()
            lemonToast.success('View successfully deleted')
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
                actions.loadDatabase()
            } catch (e: any) {
                lemonToast.error(e.message)
                actions.setEditSchemaIsLoading(false)
            }
        },
        loadDatabaseSuccess: () => {
            if (values.inEditSchemaMode) {
                actions.toggleEditSchemaMode()
            }
        },
        loadDatabaseFailure: () => {
            if (values.inEditSchemaMode) {
                actions.toggleEditSchemaMode()
            }
        },
        cancelEditSchema: () => {
            actions.toggleEditSchemaMode(false)
        },
        deleteDataWarehouseTable: async ({ tableId }) => {
            await api.dataWarehouseTables.delete(tableId)
            actions.selectRow(null)
            lemonToast.success('Table successfully deleted')
        },
    })),
])
