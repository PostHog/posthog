import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import posthog from 'posthog-js'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { DataWarehouseViewLink } from '~/types'

import { dataWarehouseJoinsLogic } from './external/dataWarehouseJoinsLogic'
import type { viewLinkLogicType } from './viewLinkLogicType'
import { ViewLinkKeyLabel } from './ViewLinkModal'
import { DatabaseSchemaField } from '~/queries/schema/schema-general'

const NEW_VIEW_LINK: DataWarehouseViewLink = {
    id: 'new',
    source_table_name: undefined,
    joining_table_name: undefined,
    field_name: undefined,
}

export interface KeySelectOption {
    value: string
    label: JSX.Element
    disabledReason?: string
}

const disabledReasonForColumn = (column: DatabaseSchemaField): string | undefined => {
    if (column.type === 'lazy_table') {
        return "Lazy tables can't be joined directly, use SQL expression to join with lazy table fields"
    }

    if (column.type === 'json') {
        return "JSON columns can't be joined directly, use SQL expression to join with JSON fields"
    }

    return undefined
}

export const viewLinkLogic = kea<viewLinkLogicType>([
    path(['scenes', 'data-warehouse', 'viewLinkLogic']),
    connect(() => ({
        values: [databaseTableListLogic, ['allTables']],
        actions: [databaseTableListLogic, ['loadDatabase'], dataWarehouseJoinsLogic, ['loadJoins']],
    })),
    actions(({ values }) => ({
        selectJoiningTable: (selectedTableName: string) => ({ selectedTableName }),
        selectSourceTable: (selectedTableName: string) => ({ selectedTableName }),
        selectSourceKey: (selectedKey: string) => ({ selectedKey, sourceTable: values.selectedSourceTable }),
        selectJoiningKey: (selectedKey: string) => ({ selectedKey, joiningTable: values.selectedJoiningTable }),
        toggleJoinTableModal: true,
        toggleEditJoinModal: (join: DataWarehouseViewLink) => ({ join }),
        toggleNewJoinModal: (join?: Partial<DataWarehouseViewLink>) => ({ join }),
        saveViewLink: (viewLink) => ({ viewLink }),
        deleteViewLink: (table, column) => ({ table, column }),
        setError: (error: string) => ({ error }),
        setFieldName: (fieldName: string) => ({ fieldName }),
        setExperimentsOptimized: (experimentsOptimized: boolean) => ({ experimentsOptimized }),
        selectExperimentsTimestampKey: (experimentsTimestampKey: string | null) => ({ experimentsTimestampKey }),
        clearModalFields: true,
    })),
    reducers({
        joinToEdit: [
            null as DataWarehouseViewLink | null,
            {
                submitViewLinkSuccess: () => null,
                clearModalFields: () => null,
                toggleNewJoinModal: () => null,
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
                toggleNewJoinModal: (_, { join }) => join?.source_table_name ?? null,
                toggleEditJoinModal: (_, { join }) => join.source_table_name ?? null,
                clearModalFields: () => null,
            },
        ],
        selectedJoiningTableName: [
            null as string | null,
            {
                selectJoiningTable: (_, { selectedTableName }) => selectedTableName,
                toggleNewJoinModal: (_, { join }) => join?.joining_table_name ?? null,
                toggleEditJoinModal: (_, { join }) => join.joining_table_name ?? null,
                clearModalFields: () => null,
            },
        ],
        selectedSourceKey: [
            null as string | null,
            {
                selectSourceKey: (_, { selectedKey }) => selectedKey,
                toggleNewJoinModal: (_, { join }) => join?.source_table_key ?? null,
                toggleEditJoinModal: (_, { join }) => join.source_table_key ?? null,
            },
        ],
        selectedJoiningKey: [
            null as string | null,
            {
                selectJoiningKey: (_, { selectedKey }) => selectedKey,
                toggleNewJoinModal: (_, { join }) => join?.joining_table_key ?? null,
                toggleEditJoinModal: (_, { join }) => join.joining_table_key ?? null,
            },
        ],
        fieldName: [
            '' as string,
            {
                setFieldName: (_, { fieldName }) => fieldName,
                selectJoiningTable: (_, { selectedTableName }) => selectedTableName.replaceAll('.', '_'),
                toggleNewJoinModal: (_, { join }) => join?.field_name ?? '',
                toggleEditJoinModal: (_, { join }) => join.field_name ?? '',
                clearModalFields: () => '',
            },
        ],
        experimentsOptimized: [
            false as boolean,
            {
                setExperimentsOptimized: (_, { experimentsOptimized }) => experimentsOptimized,
                toggleNewJoinModal: (_, { join }) => join?.configuration?.experiments_optimized ?? false,
                toggleEditJoinModal: (_, { join }) => join.configuration?.experiments_optimized ?? false,
                clearModalFields: () => false,
            },
        ],
        experimentsTimestampKey: [
            null as string | null,
            {
                selectExperimentsTimestampKey: (_, { experimentsTimestampKey }) => experimentsTimestampKey,
                toggleNewJoinModal: (_, { join }) => join?.configuration?.experiments_timestamp_key ?? null,
                toggleEditJoinModal: (_, { join }) => join.configuration?.experiments_timestamp_key ?? null,
                clearModalFields: () => null,
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
            errors: ({ source_table_name, joining_table_name }) => {
                return {
                    source_table_name: values.isNewJoin && !source_table_name ? 'Must select a table' : undefined,
                    joining_table_name: !joining_table_name ? 'Must select a table' : undefined,
                }
            },
            submit: async ({ joining_table_name, source_table_name }) => {
                if (values.joinToEdit?.id && values.selectedSourceTable) {
                    // Edit join
                    try {
                        await api.dataWarehouseViewLinks.update(values.joinToEdit.id, {
                            source_table_name: source_table_name ?? values.selectedSourceTable.name,
                            source_table_key: values.selectedSourceKey ?? undefined,
                            joining_table_name,
                            joining_table_key: values.selectedJoiningKey ?? undefined,
                            field_name: values.fieldName,
                            configuration: {
                                experiments_optimized: values.experimentsOptimized,
                                experiments_timestamp_key: values.experimentsTimestampKey ?? undefined,
                            },
                        })

                        actions.toggleJoinTableModal()
                        actions.loadJoins()

                        actions.loadDatabase()

                        posthog.capture('join updated')
                    } catch (error: any) {
                        actions.setError(error.detail)
                    }
                } else if (values.selectedSourceTable) {
                    // Create join
                    try {
                        await api.dataWarehouseViewLinks.create({
                            source_table_name: source_table_name ?? values.selectedSourceTable.name,
                            source_table_key: values.selectedSourceKey ?? undefined,
                            joining_table_name,
                            joining_table_key: values.selectedJoiningKey ?? undefined,
                            field_name: values.fieldName,
                            configuration: {
                                experiments_optimized: values.experimentsOptimized,
                                experiments_timestamp_key: values.experimentsTimestampKey ?? undefined,
                            },
                        })

                        actions.toggleJoinTableModal()
                        actions.loadJoins()

                        actions.loadDatabase()

                        posthog.capture('join created')
                    } catch (error: any) {
                        actions.setError(error.detail)
                    }
                }
            },
        },
    })),
    listeners(({ actions }) => ({
        toggleNewJoinModal: ({ join }) => {
            actions.setViewLinkValues(join ?? NEW_VIEW_LINK)
        },
        toggleEditJoinModal: ({ join }) => {
            actions.setViewLinkValues(join)
        },
        setExperimentsOptimized: ({ experimentsOptimized }) => {
            if (!experimentsOptimized) {
                actions.selectExperimentsTimestampKey(null)
            }
        },
        selectExperimentsTimestampKey: ({ experimentsTimestampKey }) => {
            if (experimentsTimestampKey) {
                actions.setExperimentsOptimized(true)
            }
        },
    })),
    selectors({
        selectedSourceTable: [
            (s) => [s.selectedSourceTableName, s.allTables],
            (selectedSourceTableName, tables) => tables.find((row) => row.name === selectedSourceTableName),
        ],
        selectedJoiningTable: [
            (s) => [s.selectedJoiningTableName, s.allTables],
            (selectedJoiningTableName, tables) => tables.find((row) => row.name === selectedJoiningTableName),
        ],
        sourceIsUsingHogQLExpression: [
            (s) => [s.selectedSourceKey, s.selectedSourceTable],
            (sourceKey, sourceTable) => {
                if (sourceKey === null) {
                    return false
                }
                const column = Object.values(sourceTable?.fields ?? {}).find((n) => n.name == sourceKey)
                return !column
            },
        ],
        joiningIsUsingHogQLExpression: [
            (s) => [s.selectedJoiningKey, s.selectedJoiningTable],
            (joiningKey, joiningTable) => {
                if (joiningKey === null) {
                    return false
                }
                const column = Object.values(joiningTable?.fields ?? {}).find((n) => n.name == joiningKey)
                return !column
            },
        ],
        tableOptions: [
            (s) => [s.allTables],
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
                return Object.values(selectedSourceTable.fields)
                    .filter((column) => column.type !== 'view')
                    .map((column) => ({
                        value: column.name,
                        label: <ViewLinkKeyLabel column={column} />,
                        disabledReason: disabledReasonForColumn(column),
                    }))
            },
        ],
        joiningTableKeys: [
            (s) => [s.selectedJoiningTable],
            (selectedJoiningTable): KeySelectOption[] => {
                if (!selectedJoiningTable) {
                    return []
                }
                return Object.values(selectedJoiningTable.fields)
                    .filter((column) => column.type !== 'view')
                    .map((column) => ({
                        value: column.name,
                        label: <ViewLinkKeyLabel column={column} />,
                        disabledReason: disabledReasonForColumn(column),
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
