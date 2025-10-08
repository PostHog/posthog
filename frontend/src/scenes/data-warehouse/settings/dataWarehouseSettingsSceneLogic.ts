import { Monaco } from '@monaco-editor/react'
import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'
import { editor } from 'monaco-editor'
import posthog from 'posthog-js'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { urls } from 'scenes/urls'

import {
    DatabaseSchemaMaterializedViewTable,
    DatabaseSchemaTable,
    DatabaseSchemaViewTable,
    DatabaseSerializedFieldType,
    HogQLQuery,
    NodeKind,
} from '~/queries/schema/schema-general'

import { dataWarehouseViewsLogic } from '../saved_queries/dataWarehouseViewsLogic'
import type { dataWarehouseSettingsSceneLogicType } from './dataWarehouseSettingsSceneLogicType'

export interface DataWarehouseSceneLogicProps {
    monaco?: Monaco | null
    editor?: editor.IStandaloneCodeEditor | null
}

export const dataWarehouseSettingsSceneLogic = kea<dataWarehouseSettingsSceneLogicType>([
    path(['scenes', 'data-warehouse', 'settings', 'dataWarehouseSceneLogic']),
    props({} as DataWarehouseSceneLogicProps),
    connect(() => ({
        values: [
            databaseTableListLogic,
            ['database', 'posthogTables', 'dataWarehouseTables', 'databaseLoading', 'views', 'viewsMapById'],
            dataWarehouseViewsLogic,
            ['dataWarehouseSavedQueryMapById', 'dataWarehouseSavedQueriesLoading'],
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
        toggleSchemaModal: true,
        setEditingView: (id: string | null) => ({ id }),
        updateView: (query: string, types: string[][]) => ({ query, types }),
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
        schemaModalIsOpen: [
            false,
            {
                toggleSchemaModal: (state) => !state,
            },
        ],
        editingView: [
            null as string | null,
            {
                setEditingView: (_, { id }) => id,
            },
        ],
    }),
    selectors({
        dataWarehouseTablesBySourceType: [
            (s) => [s.dataWarehouseTables],
            (dataWarehouseTables): Record<string, DatabaseSchemaTable[]> => {
                return dataWarehouseTables.reduce((acc: Record<string, DatabaseSchemaTable[]>, table) => {
                    const group = table.source?.source_type ?? 'S3'
                    acc[group] ??= []
                    acc[group].push(table)

                    return acc
                }, {})
            },
        ],
        dataWarehouseTablesAndViews: [
            (s) => [s.dataWarehouseTables, s.views],
            (dataWarehouseTables, views): DatabaseSchemaTable[] => {
                return [...dataWarehouseTables, ...views]
            },
        ],
        nonMaterializedViews: [
            (s) => [s.views, s.dataWarehouseSavedQueryMapById],
            (views, dataWarehouseSavedQueryMapById): DatabaseSchemaTable[] => {
                return views
                    .filter((view) => !dataWarehouseSavedQueryMapById[view.id]?.is_materialized)
                    .map((view) => ({
                        ...view,
                        type: 'view',
                    }))
            },
        ],
        materializedViews: [
            (s) => [s.views, s.dataWarehouseSavedQueryMapById],
            (views, dataWarehouseSavedQueryMapById): DatabaseSchemaMaterializedViewTable[] => {
                return views
                    .filter((view) => dataWarehouseSavedQueryMapById[view.id]?.is_materialized)
                    .map((view) => ({
                        ...view,
                        type: 'materialized_view',
                        last_run_at: dataWarehouseSavedQueryMapById[view.id]?.last_run_at,
                        status: dataWarehouseSavedQueryMapById[view.id]?.status,
                    }))
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
            lemonToast.success(`${payload?.name ?? 'View'} successfully updated`)
            if (payload) {
                router.actions.push(urls.sqlEditor(undefined, payload.id))
            }
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

                if (values.selectedRow) {
                    posthog.capture('source schema saved', {
                        name: values.selectedRow.name,
                        tableType: values.selectedRow.type,
                    })
                }
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
        toggleSchemaModal: () => {
            if (values.schemaModalIsOpen && values.selectedRow) {
                posthog.capture('source schema viewed', {
                    name: values.selectedRow.name,
                    tableType: values.selectedRow.type,
                })
            }
        },
        updateView: ({ query, types }) => {
            if (values.editingView) {
                const newViewQuery: HogQLQuery = {
                    kind: NodeKind.HogQLQuery,
                    query: query,
                }

                const oldView = values.viewsMapById[values.editingView]
                if (oldView.type === 'view') {
                    // Should always be `view`, but assert at the TS level
                    const newView: DatabaseSchemaViewTable & { types: string[][] } = {
                        ...oldView,
                        query: newViewQuery,
                        types,
                    }
                    actions.updateDataWarehouseSavedQuery(newView)
                }
            }
        },
    })),
    urlToAction(({ actions }) => ({
        '/data-warehouse/view/:id': ({ id }) => {
            actions.setEditingView(id as string)
        },
        '/data-warehouse': () => {
            actions.setEditingView(null)
        },
    })),
])
