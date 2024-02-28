import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { DataWarehouseViewLink } from '~/types'

import { dataWarehouseJoinsLogic } from './external/dataWarehouseJoinsLogic'
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
            ['filteredTables', 'dataWarehouse'],
        ],
        actions: [databaseTableListLogic, ['loadDatabase'], dataWarehouseJoinsLogic, ['loadJoins']],
    }),
    actions({
        selectJoiningTable: (selectedTableName: string) => ({ selectedTableName }),
        selectSourceTable: (selectedTableName: string) => ({ selectedTableName }),
        toggleJoinTableModal: true,
        toggleEditJoinModal: (join: DataWarehouseViewLink) => ({ join }),
        toggleNewJoinModal: true,
        saveViewLink: (viewLink) => ({ viewLink }),
        deleteViewLink: (table, column) => ({ table, column }),
        setError: (error: string) => ({ error }),
        setFieldName: (fieldName: string) => ({ fieldName }),
        clearModalFields: true,
    }),
    reducers({
        joinToEdit: [
            null as DataWarehouseViewLink | null,
            {
                submitViewLinkSuccess: () => null,
                clearModalFields: () => null,
                toggleEditJoinModal: (_, { join }) => join,
            },
        ],
        isNewJoin: [
            false as boolean,
            {
                submitViewLinkSuccess: () => false,
                toggleJoinTableModal: () => false,
                toggleEditJoinModal: () => false,
                toggleNewJoinModal: () => true,
                clearModalFields: () => false,
            },
        ],
        selectedSourceTableName: [
            null as string | null,
            {
                selectSourceTable: (_, { selectedTableName }) => selectedTableName,
                toggleEditJoinModal: (_, { join }) => join.source_table_name ?? null,
                clearModalFields: () => null,
            },
        ],
        selectedJoiningTableName: [
            null as string | null,
            {
                selectJoiningTable: (_, { selectedTableName }) => selectedTableName,
                toggleEditJoinModal: (_, { join }) => join.joining_table_name ?? null,
                clearModalFields: () => null,
            },
        ],
        fieldName: [
            '' as string,
            {
                setFieldName: (_, { fieldName }) => fieldName,
                selectJoiningTable: (_, { selectedTableName }) => selectedTableName,
                toggleEditJoinModal: (_, { join }) => join.field_name ?? '',
                clearModalFields: () => '',
            },
        ],
        isJoinTableModalOpen: [
            false,
            {
                toggleJoinTableModal: (state) => !state,
                toggleEditJoinModal: () => true,
                toggleNewJoinModal: () => true,
            },
        ],
        error: [
            null as null | string,
            {
                setError: (_, { error }) => error,
                clearModalFields: () => null,
            },
        ],
    }),
    forms(({ actions, values }) => ({
        viewLink: {
            defaults: NEW_VIEW_LINK,
            errors: ({ source_table_name, joining_table_name, joining_table_key, source_table_key }) => {
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
                    source_table_name: values.isNewJoin && !source_table_name ? 'Must select a table' : undefined,
                    joining_table_name: !joining_table_name ? 'Must select a table' : undefined,
                    source_table_key: source_table_key_err,
                    joining_table_key: joining_table_key_err,
                }
            },
            submit: async ({ joining_table_name, source_table_name, source_table_key, joining_table_key }) => {
                if (values.joinToEdit?.id && values.selectedSourceTable) {
                    // Edit join
                    try {
                        await api.dataWarehouseViewLinks.update(values.joinToEdit.id, {
                            source_table_name: source_table_name ?? values.selectedSourceTable.name,
                            source_table_key,
                            joining_table_name,
                            joining_table_key,
                            field_name: values.fieldName,
                        })

                        actions.toggleJoinTableModal()
                        actions.loadJoins()
                        // actions.loadDatabase()
                    } catch (error: any) {
                        actions.setError(error.detail)
                    }
                } else if (values.selectedSourceTable) {
                    // Create join
                    try {
                        await api.dataWarehouseViewLinks.create({
                            source_table_name: source_table_name ?? values.selectedSourceTable.name,
                            source_table_key,
                            joining_table_name,
                            joining_table_key,
                            field_name: values.fieldName,
                        })

                        actions.toggleJoinTableModal()
                        actions.loadJoins()
                        // actions.loadDatabase()
                    } catch (error: any) {
                        actions.setError(error.detail)
                    }
                }
            },
        },
    })),
    listeners(({ actions }) => ({
        toggleEditJoinModal: ({ join }) => {
            actions.setViewLinkValues(join)
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
        tableOptions: [
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
    subscriptions(({ actions }) => ({
        isJoinTableModalOpen: (isOpen) => {
            if (!isOpen) {
                actions.clearModalFields()
                actions.resetViewLink()
            }
        },
    })),
])
