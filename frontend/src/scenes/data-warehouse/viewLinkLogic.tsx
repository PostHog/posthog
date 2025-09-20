import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { subscriptions } from 'kea-subscriptions'
import posthog from 'posthog-js'

import api from 'lib/api'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'

import { hogqlQuery } from '~/queries/query'
import { DatabaseSchemaField } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { DataWarehouseViewLink } from '~/types'

import { ViewLinkKeyLabel } from './ViewLinkModal'
import { dataWarehouseJoinsLogic } from './external/dataWarehouseJoinsLogic'
import type { viewLinkLogicType } from './viewLinkLogicType'

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
        loadSourceTablePreview: (tableName: string) => ({ tableName }),
        loadJoiningTablePreview: (tableName: string) => ({ tableName }),
        setSourceTablePreviewData: (data: Record<string, any>[]) => ({ data }),
        setJoiningTablePreviewData: (data: Record<string, any>[]) => ({ data }),
        setIsJoinValid: (isValid: boolean) => ({ isValid }),
        setValidationError: (errorMessage: string) => ({ errorMessage }),
        setValidationWarning: (validationWarning: string | null) => ({ validationWarning }),
        validateJoin: () => {},
        checkKeyTypeMismatch: () => {},
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
        isJoinValidating: [
            false as boolean,
            {
                validateJoin: () => true,
                setIsJoinValid: () => false,
            },
        ],
        isJoinValid: [
            false as boolean,
            {
                setIsJoinValid: (_, { isValid }) => isValid,
                selectSourceKey: () => false,
                selectSourceTable: () => false,
                selectJoiningKey: () => false,
                selectJoiningTable: () => false,
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
                clearModalFields: () => null,
            },
        ],
        selectedJoiningKey: [
            null as string | null,
            {
                selectJoiningKey: (_, { selectedKey }) => selectedKey,
                toggleNewJoinModal: (_, { join }) => join?.joining_table_key ?? null,
                toggleEditJoinModal: (_, { join }) => join.joining_table_key ?? null,
                clearModalFields: () => null,
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
        validationError: [
            null as null | string,
            {
                setValidationError: (_, { errorMessage }) => errorMessage,
                clearModalFields: () => null,
                selectSourceKey: () => null,
                selectSourceTable: () => null,
                selectJoiningKey: () => null,
                selectJoiningTable: () => null,
            },
        ],
        validationWarning: [
            null as null | string,
            {
                setValidationWarning: (_, { validationWarning }) => validationWarning,
                clearModalFields: () => null,
                selectSourceKey: () => null,
                selectSourceTable: () => null,
                selectJoiningKey: () => null,
                selectJoiningTable: () => null,
            },
        ],
        sourceTablePreviewData: [
            [] as Record<string, any>[],
            {
                setSourceTablePreviewData: (_, { data }) => data,
                clearModalFields: () => [],
            },
        ],
        joiningTablePreviewData: [
            [] as Record<string, any>[],
            {
                setJoiningTablePreviewData: (_, { data }) => data,
                clearModalFields: () => [],
            },
        ],
        sourceTablePreviewLoading: [
            false as boolean,
            {
                loadSourceTablePreview: () => true,
                setSourceTablePreviewData: () => false,
            },
        ],
        joiningTablePreviewLoading: [
            false as boolean,
            {
                loadJoiningTablePreview: () => true,
                setJoiningTablePreviewData: () => false,
            },
        ],
    }),
    forms(({ actions, values }) => ({
        viewLink: {
            defaults: NEW_VIEW_LINK,
            errors: ({ source_table_name, source_table_key, joining_table_name, joining_table_key }) => {
                return {
                    source_table_name: values.isNewJoin && !source_table_name ? 'Must select a table' : undefined,
                    source_table_key: !source_table_key ? 'Must select a key' : undefined,
                    joining_table_name: !joining_table_name ? 'Must select a table' : undefined,
                    joining_table_key: joining_table_name && !joining_table_key ? 'Must select a key' : undefined,
                }
            },
            submit: async ({ source_table_name, source_table_key, joining_table_name, joining_table_key }) => {
                if (values.joinToEdit?.id && values.selectedSourceTable) {
                    // Edit join
                    try {
                        await api.dataWarehouseViewLinks.update(values.joinToEdit.id, {
                            source_table_name: source_table_name ?? values.selectedSourceTable.name,
                            source_table_key,
                            joining_table_name,
                            joining_table_key,
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
                            source_table_key,
                            joining_table_name,
                            joining_table_key,
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
    listeners(({ actions, values }) => ({
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
        selectSourceTable: async ({ selectedTableName }) => {
            actions.setIsJoinValid(false)
            if (selectedTableName) {
                actions.loadSourceTablePreview(selectedTableName)
            }
        },
        selectJoiningTable: async ({ selectedTableName }) => {
            actions.setIsJoinValid(false)
            if (selectedTableName) {
                actions.loadJoiningTablePreview(selectedTableName)
            }
        },
        checkKeyTypeMismatch: () => {
            if (values.selectedSourceKey && values.selectedJoiningKey) {
                const sourceColumn = Object.values(values.selectedSourceTable?.fields ?? {}).find(
                    (field) => field.name === values.selectedSourceKey
                )
                const joiningColumn = Object.values(values.selectedJoiningTable?.fields ?? {}).find(
                    (field) => field.name === values.selectedJoiningKey
                )
                const sourceKeyDataType = sourceColumn?.type ?? 'unknown'
                const joiningKeyDataType = joiningColumn?.type ?? 'unknown'
                const validationWarning =
                    sourceKeyDataType !== joiningKeyDataType
                        ? `Key types don't match: Source table key is from type ${sourceKeyDataType} but joining table key is from type ${joiningKeyDataType}`
                        : null
                actions.setValidationWarning(validationWarning)
            }
        },
        selectSourceKey: () => {
            actions.checkKeyTypeMismatch()
        },
        selectJoiningKey: () => {
            actions.checkKeyTypeMismatch()
        },
        loadSourceTablePreview: async ({ tableName }) => {
            await loadTablePreviewData(tableName, actions.setSourceTablePreviewData)
        },
        loadJoiningTablePreview: async ({ tableName }) => {
            await loadTablePreviewData(tableName, actions.setJoiningTablePreviewData)
        },
        validateJoin: async () => {
            if (
                !values.selectedSourceTableName ||
                !values.selectedJoiningTableName ||
                !values.selectedSourceKey ||
                !values.selectedJoiningKey
            ) {
                actions.setIsJoinValid(false)
                return
            }
            try {
                const sourceTable = hogql.identifier(values.selectedSourceTableName)
                const sourceKey = hogql.identifier(values.selectedSourceKey)
                const joiningTable = hogql.identifier(values.selectedJoiningTableName)
                const joiningKey = hogql.identifier(values.selectedJoiningKey)
                const response = await hogqlQuery(
                    hogql`
                    SELECT ${sourceTable}.${sourceKey}, ${joiningTable}.${joiningKey}
                    FROM ${sourceTable}
                    JOIN ${joiningTable}
                    ON ${sourceTable}.${sourceKey} = ${joiningTable}.${joiningKey}
                    LIMIT 10`
                )
                if (response.results.length === 0) {
                    actions.setValidationWarning('No matching data found between source and joining tables.')
                    actions.setIsJoinValid(false)
                } else {
                    actions.setIsJoinValid(true)
                }
            } catch (error: any) {
                actions.setValidationError(error.detail)
                actions.setIsJoinValid(false)
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

async function loadTablePreviewData(
    tableName: string,
    setDataAction: (data: Record<string, any>[]) => void
): Promise<void> {
    try {
        const response = await hogqlQuery(hogql`SELECT * FROM ${hogql.identifier(tableName)} LIMIT 10`)
        const transformedData = (response.results || []).map((row: any[]) =>
            Object.fromEntries((response.columns || []).map((column: string, index: number) => [column, row[index]]))
        )
        setDataAction(transformedData)
    } catch (error) {
        posthog.captureException(error)
        setDataAction([])
    }
}
