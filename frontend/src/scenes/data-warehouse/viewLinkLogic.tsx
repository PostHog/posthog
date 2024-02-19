import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { DataWarehouseViewLink } from '~/types'

import { dataWarehouseSavedQueriesLogic } from './saved_queries/dataWarehouseSavedQueriesLogic'
import { DataWarehouseRowType, DataWarehouseTableType } from './types'
import type { viewLinkLogicType } from './viewLinkLogicType'
import { ViewLinkKeyLabel } from './ViewLinkModal'

const NEW_VIEW_LINK: DataWarehouseViewLink = {
    id: 'new',
    source_table_name: undefined,
    source_table_key: undefined,
    joining_table_name: undefined,
    joining_table_key: undefined,
    field_name: undefined,
}

export interface KeySelectOption {
    value: string
    label: JSX.Element
}

export const viewLinkLogic = kea<viewLinkLogicType>([
    path(['scenes', 'data-warehouse', 'viewLinkLogic']),
    connect({
        values: [
            dataWarehouseSavedQueriesLogic,
            ['savedQueries'],
            databaseTableListLogic,
            ['tableOptions', 'filteredTables', 'dataWarehouse'],
        ],
        actions: [databaseTableListLogic, ['loadDatabase']],
    }),
    actions({
        selectJoiningTable: (selectedTableName: string) => ({ selectedTableName }),
        selectSourceTable: (selectedTableName: string) => ({ selectedTableName }),
        toggleJoinTableModal: true,
        saveViewLink: (viewLink) => ({ viewLink }),
        deleteViewLink: (table, column) => ({ table, column }),
        setError: (error: string) => ({ error }),
        setFieldName: (fieldName: string) => ({ fieldName }),
    }),
    reducers({
        selectedSourceTableName: [
            null as string | null,
            {
                selectSourceTable: (_, { selectedTableName }) => selectedTableName,
            },
        ],
        selectedJoiningTableName: [
            null as string | null,
            {
                selectJoiningTable: (_, { selectedTableName }) => selectedTableName,
            },
        ],
        fieldName: [
            '' as string,
            {
                setFieldName: (_, { fieldName }) => fieldName,
                selectJoiningTable: (_, { selectedTableName }) => selectedTableName,
            },
        ],
        isJoinTableModalOpen: [
            false,
            {
                toggleJoinTableModal: (state) => !state,
            },
        ],
        error: [
            null as null | string,
            {
                setError: (_, { error }) => error,
            },
        ],
    }),
    forms(({ actions, values }) => ({
        viewLink: {
            defaults: NEW_VIEW_LINK,
            errors: ({ joining_table_name, joining_table_key, source_table_key }) => {
                let joining_table_key_err: string | undefined = undefined
                let source_table_key_err: string | undefined = undefined

                if (!joining_table_key) {
                    joining_table_key_err = 'Must select a join key'
                }

                if (!source_table_key) {
                    source_table_key_err = 'Must select a join key'
                }

                if (
                    joining_table_key &&
                    source_table_key &&
                    values.selectedJoiningTable?.columns?.find((n) => n.key == joining_table_key)?.type !==
                        values.selectedSourceTable?.columns?.find((n) => n.key == source_table_key)?.type
                ) {
                    joining_table_key_err = 'Join key types must match'
                    source_table_key_err = 'Join key types must match'
                }

                return {
                    joining_table_name: !joining_table_name ? 'Must select a table' : undefined,
                    to_join_key: joining_table_key_err,
                    from_join_key: source_table_key_err,
                }
            },
            submit: async ({ joining_table_name, source_table_key, joining_table_key }) => {
                if (values.selectedSourceTable) {
                    try {
                        await api.dataWarehouseViewLinks.create({
                            source_table_name: values.selectedSourceTable.name,
                            source_table_key,
                            joining_table_name,
                            joining_table_key,
                            field_name: values.fieldName,
                        })

                        actions.toggleJoinTableModal()
                        // actions.loadDatabase()
                    } catch (error: any) {
                        actions.setError(error.detail)
                    }
                }
            },
        },
    })),
    listeners(({ values, actions }) => ({
        deleteViewLink: async ({ table, column }) => {
            // const matchedSavedQuery = values.savedQueries.find((savedQuery) => {
            //     return savedQuery.name === column
            // })
            // const matchedViewLink = values.viewLinks.find((viewLink) => {
            //     return viewLink.table === table && matchedSavedQuery && matchedSavedQuery.id === viewLink.saved_query
            // })
            // if (!matchedViewLink) {
            //     lemonToast.error(`Error deleting view link`)
            //     return
            // }
            // await api.dataWarehouseViewLinks.delete(matchedViewLink.id)
            // actions.loadDatabase()
        },
    })),
    selectors({
        tables: [
            (s) => [s.dataWarehouse, s.filteredTables],
            (warehouseTables, posthogTables): DataWarehouseTableType[] => {
                const mappedWarehouseTables = (warehouseTables?.results ?? []).map(
                    (table) =>
                        ({
                            id: table.id,
                            name: table.name,
                            columns: table.columns,
                            payload: table,
                            type: DataWarehouseRowType.ExternalTable,
                        } as DataWarehouseTableType)
                )

                const mappedPosthogTables = posthogTables.map(
                    (table) =>
                        ({
                            id: table.name,
                            name: table.name,
                            columns: table.columns,
                            payload: table,
                            type: DataWarehouseRowType.PostHogTable,
                        } as DataWarehouseTableType)
                )

                return mappedPosthogTables.concat(mappedWarehouseTables)
            },
        ],
        selectedSourceTable: [
            (s) => [s.selectedSourceTableName, s.tables],
            (selectedSourceTableName, tables) => tables.find((row) => row.name === selectedSourceTableName),
        ],
        selectedJoiningTable: [
            (s) => [s.selectedJoiningTableName, s.tables],
            (selectedJoiningTableName, tables) => tables.find((row) => row.name === selectedJoiningTableName),
        ],
        joiningTableOptions: [
            (s) => [s.tables],
            (tables) =>
                tables.map((table) => ({
                    value: table.name,
                    label: table.name,
                })),
        ],
        sourceTableKeys: [
            (s) => [s.selectedSourceTable],
            (selectedSourceTable): KeySelectOption[] => {
                if (!selectedSourceTable) {
                    return []
                }
                return selectedSourceTable.columns
                    .filter((column) => column.type !== 'view')
                    .map((column) => ({
                        value: column.key,
                        label: <ViewLinkKeyLabel column={column} />,
                    }))
            },
        ],
        joiningTableKeys: [
            (s) => [s.selectedJoiningTable],
            (selectedJoiningTable): KeySelectOption[] => {
                if (!selectedJoiningTable) {
                    return []
                }
                return selectedJoiningTable.columns
                    .filter((column) => column.type !== 'view')
                    .map((column) => ({
                        value: column.key,
                        label: <ViewLinkKeyLabel column={column} />,
                    }))
            },
        ],
        sqlCodeSnippet: [
            (s) => [s.selectedSourceTableName, s.selectedJoiningTableName, s.fieldName],
            (selectedSourceTableName, joiningTableName, fieldName) => {
                if (!selectedSourceTableName || !joiningTableName) {
                    return null
                }

                const tableAlias = selectedSourceTableName[0]
                return `SELECT ${tableAlias}.${fieldName || ''} FROM ${selectedSourceTableName} ${tableAlias}`
            },
        ],
    }),
])
