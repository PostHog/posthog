import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import type { SimpleOption } from 'lib/components/TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils/objects'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { propertyDefinitionsModel, updatePropertyDefinitions } from '~/models/propertyDefinitionsModel'
import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'
import type {
    AccountsTableCustomPropertyDefinition,
    AccountsTableRelationshipDefinition,
} from '~/queries/schema/schema-general'
import { AccountsTableAccountField, DatabaseSchemaField, DatabaseSchemaTable } from '~/queries/schema/schema-general'
import { PropertyDefinitionType, PropertyType } from '~/types'

import {
    accountRelationshipDefinitionsList,
    customPropertyDefinitionsList,
} from 'products/customer_analytics/frontend/generated/api'

import type { AccountsTableQueryResponse } from '../../../../../frontend/src/queries/schema/schema-general'
import { ACCOUNT_FIELD_TAXONOMIC_OPTIONS, propertyTypeForDisplayType } from './accountsPropertyFilters'

export const ACCOUNTS_NAME_COLUMN = 'name'
export const ACCOUNTS_TAGS_COLUMN = 'accounts.tags.names AS tag_names'
const LEGACY_ACCOUNTS_TAGS_NAME_COLUMN = 'accounts.tags.names AS names'
const LEGACY_ACCOUNTS_TAGS_ACCOUNT_ID_COLUMN = 'accounts.tags.account_id AS account_id'

export const ACCOUNTS_DEFAULT_COLUMNS: string[] = [
    ACCOUNTS_NAME_COLUMN,
    ACCOUNTS_TAGS_COLUMN,
    'accounts.notebooks.count AS notebook_count',
]

export function normalizeAccountColumns(columns: string[]): string[] {
    const normalizedColumns = columns.flatMap((column) => {
        if (column === LEGACY_ACCOUNTS_TAGS_NAME_COLUMN) {
            return [ACCOUNTS_TAGS_COLUMN]
        }
        if (column === LEGACY_ACCOUNTS_TAGS_ACCOUNT_ID_COLUMN) {
            return []
        }
        return [column]
    })
    const deduplicatedColumns = [...new Set(normalizedColumns)]
    return deduplicatedColumns.includes(ACCOUNTS_NAME_COLUMN)
        ? deduplicatedColumns
        : [ACCOUNTS_NAME_COLUMN, ...deduplicatedColumns]
}

export function diffColumnConfiguration(
    previous: string[],
    next: string[]
): { changed: boolean; added: number; removed: number; reordered: boolean } {
    const previousSet = new Set(previous)
    const nextSet = new Set(next)
    const added = next.filter((column) => !previousSet.has(column)).length
    const removed = previous.filter((column) => !nextSet.has(column)).length
    const reordered = !objectsEqual(
        previous.filter((column) => nextSet.has(column)),
        next.filter((column) => previousSet.has(column))
    )
    return { changed: added > 0 || removed > 0 || reordered, added, removed, reordered }
}

export const ACCOUNTS_COLUMN_CONFIG_KEY = 'customer_analytics_accounts_columns'

export const ACCOUNTS_ACCOUNTS_TABLE_NAME = 'system.accounts'

export type AccountColumnGroupKey = 'account_properties' | 'custom_properties' | 'relationships' | `accounts.${string}`

export const ALL_COLUMNS_KEY = 'all'
export type PickerGroupKey = AccountColumnGroupKey | typeof ALL_COLUMNS_KEY

// Persisted aliases must keep this format so saved views can resolve their columns.
export function customPropertyAlias(id: string): string {
    return `cp_${id.replace(/-/g, '')}`
}

export function relationshipAlias(id: string): string {
    return `rel_${id.replace(/-/g, '')}`
}

export type AccountColumnDisplayMode = 'sparkline' | 'trend'

export interface AccountColumnDisplayConfig {
    mode: AccountColumnDisplayMode
    window_days: number
}

// Use definition IDs so the config survives column removal and re-addition.
export type AccountColumnDisplayState = Record<string, AccountColumnDisplayConfig>

export const COLUMN_DISPLAY_WINDOW_OPTIONS = [7, 14, 30, 90] as const
export const DEFAULT_COLUMN_DISPLAY_WINDOW_DAYS = 7

const CUSTOM_PROPERTY_COLUMN_REGEX = /^accounts\.custom_properties\.values\.`([0-9a-fA-F-]+)` AS (cp_[0-9a-fA-F]+)$/

// Keep stored column strings scalar so saved column identities stay stable.
export function applyColumnDisplayToSelect(columns: string[], columnDisplay: AccountColumnDisplayState): string[] {
    if (Object.keys(columnDisplay).length === 0) {
        return columns
    }
    return columns.map((column) => {
        const match = column.match(CUSTOM_PROPERTY_COLUMN_REGEX)
        if (!match || !columnDisplay[match[1]]) {
            return column
        }
        return `accounts.custom_properties_history.values.\`${match[1]}\` AS ${match[2]}`
    })
}

function getRelationshipColumn(definitionId: string): string {
    return `accounts.relationships.values.\`${definitionId}\` AS ${relationshipAlias(definitionId)}`
}

export type AccountColumnOption = {
    name: string
    expression: string
    type?: string
}

export type AccountColumnGroup = {
    key: AccountColumnGroupKey
    label: string
    options: AccountColumnOption[]
}

export type AccountPickerColumnOption = AccountColumnOption & { groupLabel: string; isSelected: boolean }

export function filterColumnOptions(
    groups: AccountColumnGroup[],
    activeGroup: AccountColumnGroup | null,
    search: string,
    selectColumns: string[]
): AccountPickerColumnOption[] {
    const searchableGroups = activeGroup ? [activeGroup] : groups
    const query = search.trim().toLowerCase()
    const selected = new Set(selectColumns)
    return searchableGroups.flatMap((group) =>
        group.options
            .filter((option) => !query || option.name.toLowerCase().includes(query))
            .map((option) => ({
                ...option,
                groupLabel: group.label,
                isSelected: selected.has(option.expression),
            }))
    )
}

const JOIN_FIELD_TYPES = new Set(['lazy_table', 'virtual_table', 'view', 'materialized_view'])

// Definition-driven groups replace these raw joins.
const HIDDEN_JOIN_GROUPS = new Set(['custom_properties', 'relationships'])
const POSTGRES_BACKED_JOIN_GROUPS = new Set(['notebooks'])
const POSTGRES_BACKED_ACCOUNT_FIELDS = new Set<string>(Object.values(AccountsTableAccountField))

const SKIPPED_DIRECT_FIELD_TYPES = new Set([
    'lazy_table',
    'virtual_table',
    'view',
    'materialized_view',
    'field_traverser',
    'unknown',
])

function buildJoinOptions(
    fieldName: string,
    fields: string[],
    joinedTable: DatabaseSchemaTable | undefined
): AccountColumnOption[] {
    return fields.map((name) => ({
        name,
        expression: `accounts.${fieldName}.${name} AS ${name}`,
        type: joinedTable?.fields?.[name]?.type,
    }))
}

function joinOptionsFromSchema(
    field: DatabaseSchemaField,
    joinedTable: DatabaseSchemaTable | undefined
): AccountColumnOption[] {
    const names: string[] = field.fields ?? Object.keys(joinedTable?.fields ?? {})
    return buildJoinOptions(field.name, names, joinedTable)
}

function customPropertyOptions(definitions: AccountsTableCustomPropertyDefinition[]): AccountColumnOption[] {
    return definitions.map((definition) => ({
        name: definition.name,
        type: definition.display_type,
        expression: `accounts.custom_properties.values.\`${definition.id}\` AS ${customPropertyAlias(definition.id)}`,
    }))
}

function relationshipOptions(definitions: AccountsTableRelationshipDefinition[]): AccountColumnOption[] {
    return definitions.map((definition) => ({
        name: definition.name,
        expression: getRelationshipColumn(definition.id),
    }))
}

export function buildAccountColumnGroups(
    allTablesMap: Record<string, DatabaseSchemaTable> | null | undefined,
    customPropertyDefinitions: AccountsTableCustomPropertyDefinition[] = [],
    relationshipDefinitions: AccountsTableRelationshipDefinition[] = []
): AccountColumnGroup[] {
    const accountsTable = allTablesMap?.[ACCOUNTS_ACCOUNTS_TABLE_NAME]
    const directOptions: AccountColumnOption[] = []
    const joinGroups: AccountColumnGroup[] = []
    const seenJoinKeys = new Set<string>()

    const addJoinGroup = (fieldName: string, options: AccountColumnOption[]): void => {
        const key = `accounts.${fieldName}` as AccountColumnGroupKey
        if (seenJoinKeys.has(key)) {
            return
        }
        seenJoinKeys.add(key)
        // Hide the internal accounts prefix from picker labels.
        joinGroups.push({ key, label: fieldName, options })
    }

    if (accountsTable) {
        for (const field of Object.values(accountsTable.fields)) {
            if (JOIN_FIELD_TYPES.has(field.type)) {
                const joinedTable = field.table ? allTablesMap?.[field.table] : undefined
                if (field.name === 'tags') {
                    directOptions.push({
                        name: 'tags',
                        expression: ACCOUNTS_TAGS_COLUMN,
                        type: 'tags',
                    })
                    continue
                }
                if (HIDDEN_JOIN_GROUPS.has(field.name) || !POSTGRES_BACKED_JOIN_GROUPS.has(field.name)) {
                    continue
                }
                addJoinGroup(field.name, joinOptionsFromSchema(field, joinedTable))
                continue
            }
            if (SKIPPED_DIRECT_FIELD_TYPES.has(field.type) || !POSTGRES_BACKED_ACCOUNT_FIELDS.has(field.name)) {
                continue
            }
            directOptions.push({
                name: field.name,
                expression: field.hogql_value || field.name,
                type: field.type,
            })
        }
    }

    const customPropertyGroups: AccountColumnGroup[] =
        customPropertyDefinitions.length > 0
            ? [
                  {
                      key: 'custom_properties',
                      label: 'Custom properties',
                      options: customPropertyOptions(customPropertyDefinitions),
                  },
              ]
            : []
    const relationshipGroups: AccountColumnGroup[] =
        relationshipDefinitions.length > 0
            ? [
                  {
                      key: 'relationships',
                      label: 'Relationships',
                      options: relationshipOptions(relationshipDefinitions),
                  },
              ]
            : []

    return [
        { key: 'account_properties', label: 'Account properties', options: directOptions },
        ...relationshipGroups,
        ...customPropertyGroups,
        ...joinGroups,
    ]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountsColumnConfigLogicValues {
    allTablesMap: Record<string, DatabaseSchemaTable> // databaseTableListLogic
    databaseLoading: boolean // databaseTableListLogic
    currentProjectId: number | null // projectLogic
    currentTeamId: number | null // teamLogic
    accountsColumnGroups: AccountColumnGroup[]
    activePickerGroup: AccountColumnGroup | null
    aliasToDefinition: Record<string, AccountsTableCustomPropertyDefinition>
    aliasToRelationshipDefinition: Record<string, AccountsTableRelationshipDefinition>
    columnConfiguratorVisible: boolean
    columnDisplay: AccountColumnDisplayState
    customPropertyCatalog: AccountsTableCustomPropertyDefinition[]
    customPropertyCatalogLoaded: boolean
    customPropertyCatalogLoading: boolean
    customPropertyCatalogProjectId: number | null
    customPropertyDefinitions: AccountsTableCustomPropertyDefinition[]
    customPropertyDefinitionsById: Record<string, AccountsTableCustomPropertyDefinition>
    customPropertyDefinitionsError: string | null
    customPropertyDefinitionsLoaded: boolean
    customPropertyDefinitionsLoading: boolean
    customPropertyTaxonomicOptions: (SimpleOption & {
        description?: string
        id: string
        is_canonical?: boolean
        property_type: PropertyType
    })[]
    defaultSelectColumns: string[]
    displayByAlias: AccountColumnDisplayState
    editingColumn: string | null
    editingColumnIndex: number | null
    filteredColumnOptions: AccountPickerColumnOption[]
    pickerGroupKey: PickerGroupKey
    pickerSearch: string
    pickerSearchPlaceholder: string
    querySelectColumns: string[]
    relationshipCatalog: AccountsTableRelationshipDefinition[]
    relationshipCatalogLoaded: boolean
    relationshipCatalogLoading: boolean
    relationshipCatalogProjectId: number | null
    relationshipDefinitions: AccountsTableRelationshipDefinition[]
    relationshipDefinitionsById: Record<string, AccountsTableRelationshipDefinition>
    relationshipDefinitionsError: string | null
    relationshipDefinitionsLoaded: boolean
    relationshipDefinitionsLoading: boolean
    relationshipTaxonomicOptions: (SimpleOption & {
        id: string
        property_type: PropertyType
    })[]
    renderSelectColumns: string[]
    selectColumns: string[]
    tableColumnResponse: {
        definitionIds: string[]
        requested: string[] | undefined
    } | null
    tableCustomPropertyDefinitions: AccountsTableCustomPropertyDefinition[]
    tableRelationshipDefinitions: AccountsTableRelationshipDefinition[]
    useDefaultColumns: boolean
    visibleColumnNames: string[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountsColumnConfigLogicActions {
    ensureAllTableFields: () => {
        value: true
    } // databaseTableListLogic
    loadDatabase: (
        args_0?:
            | {
                  force?: boolean
                  shallow?: boolean
              }
            | undefined
    ) => {
        force?: boolean
        shallow?: boolean
    } // databaseTableListLogic
    ensureDefinitionsLoaded: () => {
        value: true
    }
    hideColumnConfigurator: () => {
        value: true
    }
    hydrateTableDefinitions: (
        response: import('~/queries/schema/schema-general').AccountsTableQueryResponse,
        requestedColumns?: string[]
    ) => {
        requestedColumns: string[] | undefined
        response: AccountsTableQueryResponse
    }
    loadCustomPropertyDefinitions: (params?: { projectId?: number | null }) => {
        projectId?: number | null
    }
    loadCustomPropertyDefinitionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCustomPropertyDefinitionsSuccess: (
        customPropertyCatalog: AccountsTableCustomPropertyDefinition[],
        payload?: {
            projectId?: number | null
        }
    ) => {
        customPropertyCatalog: AccountsTableCustomPropertyDefinition[]
        payload?: {
            projectId?: number | null
        }
    }
    loadRelationshipDefinitions: (params?: { projectId?: number | null }) => {
        projectId?: number | null
    }
    loadRelationshipDefinitionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRelationshipDefinitionsSuccess: (
        relationshipCatalog: AccountsTableRelationshipDefinition[],
        payload?: {
            projectId?: number | null
        }
    ) => {
        relationshipCatalog: AccountsTableRelationshipDefinition[]
        payload?: {
            projectId?: number | null
        }
    }
    moveColumn: (
        oldIndex: number,
        newIndex: number
    ) => {
        newIndex: number
        oldIndex: number
    }
    resetColumns: () => {
        value: true
    }
    resetDefinitionCatalogs: () => {
        value: true
    }
    restoreSelectColumns: (columns: string[]) => {
        columns: string[]
    }
    selectColumn: (column: string) => {
        column: string
    }
    setColumnDisplay: (
        definitionId: string,
        config: AccountColumnDisplayConfig | null
    ) => {
        config: AccountColumnDisplayConfig | null
        definitionId: string
    }
    setColumnDisplayConfig: (config: AccountColumnDisplayState) => {
        config: AccountColumnDisplayState
    }
    setDefaultSelectColumns: (columns: string[]) => {
        columns: string[]
    }
    setEditingColumnIndex: (index: number | null) => {
        index: number | null
    }
    setPickerGroupKey: (key: PickerGroupKey) => {
        key: PickerGroupKey
    }
    setPickerSearch: (search: string) => {
        search: string
    }
    setSelectColumns: (columns: string[]) => {
        columns: string[]
    }
    showColumnConfigurator: () => {
        value: true
    }
    unselectColumn: (column: string) => {
        column: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface accountsColumnConfigLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        customPropertyDefinitions: (
            customPropertyCatalog: AccountsTableCustomPropertyDefinition[],
            customPropertyCatalogProjectId: number | null,
            currentProjectId: number | null
        ) => AccountsTableCustomPropertyDefinition[]
        customPropertyDefinitionsLoaded: (
            customPropertyCatalogLoaded: boolean,
            customPropertyCatalogProjectId: number | null,
            currentProjectId: number | null
        ) => boolean
        customPropertyDefinitionsLoading: (
            customPropertyCatalogLoading: boolean,
            customPropertyCatalogProjectId: number | null,
            currentProjectId: number | null
        ) => boolean
        relationshipDefinitions: (
            relationshipCatalog: AccountsTableRelationshipDefinition[],
            relationshipCatalogProjectId: number | null,
            currentProjectId: number | null
        ) => AccountsTableRelationshipDefinition[]
        relationshipDefinitionsLoaded: (
            relationshipCatalogLoaded: boolean,
            relationshipCatalogProjectId: number | null,
            currentProjectId: number | null
        ) => boolean
        relationshipDefinitionsLoading: (
            relationshipCatalogLoading: boolean,
            relationshipCatalogProjectId: number | null,
            currentProjectId: number | null
        ) => boolean
        defaultSelectColumns: (
            relationshipDefinitionsById: Record<string, AccountsTableRelationshipDefinition>
        ) => string[]
        querySelectColumns: (selectColumns: string[], columnDisplay: AccountColumnDisplayState) => string[]
        renderSelectColumns: (
            querySelectColumns: string[],
            tableColumnResponse: {
                definitionIds: string[]
                requested: string[] | undefined
            } | null,
            useDefaultColumns: boolean
        ) => string[]
        visibleColumnNames: (renderSelectColumns: string[]) => string[]
        accountsColumnGroups: (
            allTablesMap: Record<string, DatabaseSchemaTable>,
            customPropertyDefinitions: AccountsTableCustomPropertyDefinition[],
            relationshipDefinitions: AccountsTableRelationshipDefinition[]
        ) => AccountColumnGroup[]
        activePickerGroup: (
            accountsColumnGroups: AccountColumnGroup[],
            pickerGroupKey: PickerGroupKey
        ) => AccountColumnGroup | null
        filteredColumnOptions: (
            accountsColumnGroups: AccountColumnGroup[],
            activePickerGroup: AccountColumnGroup | null,
            pickerSearch: string,
            selectColumns: string[]
        ) => AccountPickerColumnOption[]
        pickerSearchPlaceholder: (activePickerGroup: AccountColumnGroup | null) => string
        customPropertyDefinitionsById: (
            customPropertyDefinitions: AccountsTableCustomPropertyDefinition[],
            tableCustomPropertyDefinitions: AccountsTableCustomPropertyDefinition[]
        ) => Record<string, AccountsTableCustomPropertyDefinition>
        editingColumn: (selectColumns: string[], editingColumnIndex: number | null) => string | null
        displayByAlias: (columnDisplay: AccountColumnDisplayState) => AccountColumnDisplayState
        aliasToDefinition: (
            customPropertyDefinitionsById: Record<string, AccountsTableCustomPropertyDefinition>
        ) => Record<string, AccountsTableCustomPropertyDefinition>
        relationshipDefinitionsById: (
            relationshipDefinitions: AccountsTableRelationshipDefinition[],
            tableRelationshipDefinitions: AccountsTableRelationshipDefinition[]
        ) => Record<string, AccountsTableRelationshipDefinition>
        relationshipTaxonomicOptions: (
            relationshipDefinitionsById: Record<string, AccountsTableRelationshipDefinition>
        ) => (SimpleOption & {
            id: string
            property_type: PropertyType
        })[]
        customPropertyTaxonomicOptions: (
            customPropertyDefinitionsById: Record<string, AccountsTableCustomPropertyDefinition>
        ) => (SimpleOption & {
            description?: string
            id: string
            is_canonical?: boolean
            property_type: PropertyType
        })[]
        aliasToRelationshipDefinition: (
            relationshipDefinitionsById: Record<string, AccountsTableRelationshipDefinition>
        ) => Record<string, AccountsTableRelationshipDefinition>
    }
}

export type accountsColumnConfigLogicType = MakeLogicType<
    accountsColumnConfigLogicValues,
    accountsColumnConfigLogicActions,
    Record<string, any>,
    accountsColumnConfigLogicMeta
>

export const accountsColumnConfigLogic = kea<accountsColumnConfigLogicType>([
    path(['scenes', 'customerAnalytics', 'accounts', 'accountsColumnConfigLogic']),
    connect(() => ({
        values: [
            teamLogic,
            ['currentTeamId'],
            projectLogic,
            ['currentProjectId'],
            databaseTableListLogic,
            ['allTablesMap', 'databaseLoading'],
        ],
        actions: [databaseTableListLogic, ['loadDatabase', 'ensureAllTableFields']],
        // Keep seeded property definitions mounted for the filter picker.
        logic: [propertyDefinitionsModel],
    })),
    actions({
        ensureDefinitionsLoaded: true,
        resetDefinitionCatalogs: true,
        hydrateTableDefinitions: (
            response: import('~/queries/schema/schema-general').AccountsTableQueryResponse,
            requestedColumns?: string[]
        ) => ({ response, requestedColumns }),
        setSelectColumns: (columns: string[]) => ({ columns }),
        setDefaultSelectColumns: (columns: string[]) => ({ columns }),
        restoreSelectColumns: (columns: string[]) => ({ columns }),
        selectColumn: (column: string) => ({ column }),
        unselectColumn: (column: string) => ({ column }),
        moveColumn: (oldIndex: number, newIndex: number) => ({ oldIndex, newIndex }),
        resetColumns: true,
        showColumnConfigurator: true,
        hideColumnConfigurator: true,
        setColumnDisplay: (definitionId: string, config: AccountColumnDisplayConfig | null) => ({
            definitionId,
            config,
        }),
        setColumnDisplayConfig: (config: AccountColumnDisplayState) => ({ config }),
        setEditingColumnIndex: (index: number | null) => ({ index }),
        setPickerGroupKey: (key: PickerGroupKey) => ({ key }),
        setPickerSearch: (search: string) => ({ search }),
    }),
    reducers({
        tableColumnResponse: [
            null as { requested: string[] | undefined; definitionIds: string[] } | null,
            {
                hydrateTableDefinitions: (_, { response, requestedColumns }) => ({
                    requested: requestedColumns,
                    definitionIds: (response.columns ?? []).flatMap((column) =>
                        'definitionId' in column ? [column.definitionId] : []
                    ),
                }),
                resetDefinitionCatalogs: () => null,
            },
        ],
        tableCustomPropertyDefinitions: [
            [] as AccountsTableCustomPropertyDefinition[],
            {
                hydrateTableDefinitions: (_, { response }) => response.customPropertyDefinitions ?? [],
                resetDefinitionCatalogs: () => [],
            },
        ],
        tableRelationshipDefinitions: [
            [] as AccountsTableRelationshipDefinition[],
            {
                hydrateTableDefinitions: (_, { response }) => response.relationshipDefinitions ?? [],
                resetDefinitionCatalogs: () => [],
            },
        ],
        useDefaultColumns: [
            true,
            {
                resetColumns: () => true,
                setDefaultSelectColumns: () => true,
                restoreSelectColumns: () => false,
                setSelectColumns: () => false,
                selectColumn: () => false,
                unselectColumn: () => false,
                moveColumn: () => false,
            },
        ],
        selectColumns: [
            [...ACCOUNTS_DEFAULT_COLUMNS],
            {
                setSelectColumns: (_, { columns }) => normalizeAccountColumns(columns),
                setDefaultSelectColumns: (_, { columns }) => normalizeAccountColumns(columns),
                restoreSelectColumns: (_, { columns }) => normalizeAccountColumns(columns),
                selectColumn: (state, { column }) => (state.includes(column) ? state : [...state, column]),
                unselectColumn: (state, { column }) =>
                    column === ACCOUNTS_NAME_COLUMN ? state : state.filter((c) => c !== column),
                moveColumn: (state, { oldIndex, newIndex }) => {
                    if (oldIndex === newIndex || oldIndex < 0 || oldIndex >= state.length) {
                        return state
                    }
                    const next = [...state]
                    const [removed] = next.splice(oldIndex, 1)
                    next.splice(newIndex, 0, removed)
                    return next
                },
                resetColumns: () => [...ACCOUNTS_DEFAULT_COLUMNS],
            },
        ],
        // Clear the editor when the column index can change.
        editingColumnIndex: [
            null as number | null,
            {
                setEditingColumnIndex: (_, { index }) => index,
                setSelectColumns: () => null,
                setDefaultSelectColumns: () => null,
                restoreSelectColumns: () => null,
                unselectColumn: () => null,
                moveColumn: () => null,
                resetColumns: () => null,
                hideColumnConfigurator: () => null,
            },
        ],
        columnConfiguratorVisible: [
            false,
            {
                showColumnConfigurator: () => true,
                hideColumnConfigurator: () => false,
            },
        ],
        pickerGroupKey: [
            ALL_COLUMNS_KEY as PickerGroupKey,
            {
                setPickerGroupKey: (_, { key }) => key,
            },
        ],
        pickerSearch: [
            '',
            {
                setPickerSearch: (_, { search }) => search,
                // Clear searches when changing categories to avoid hiding results.
                setPickerGroupKey: () => '',
            },
        ],
        columnDisplay: [
            {} as AccountColumnDisplayState,
            {
                setColumnDisplay: (state, { definitionId, config }) => {
                    if (!config) {
                        const { [definitionId]: _removed, ...rest } = state
                        return rest
                    }
                    return { ...state, [definitionId]: config }
                },
                setColumnDisplayConfig: (_, { config }) => config,
            },
        ],
    }),
    loaders(({ values }) => ({
        customPropertyCatalog: [
            [] as AccountsTableCustomPropertyDefinition[],
            {
                loadCustomPropertyDefinitions: async (
                    params: { projectId?: number | null } = {},
                    breakpoint
                ): Promise<AccountsTableCustomPropertyDefinition[]> => {
                    const projectId = params.projectId ?? values.currentProjectId
                    const response = await customPropertyDefinitionsList(String(projectId), { pagination: 'none' })
                    breakpoint()
                    return response.results.filter(
                        (definition) => !definition.target_type || definition.target_type === 'account'
                    )
                },
            },
        ],
        relationshipCatalog: [
            [] as AccountsTableRelationshipDefinition[],
            {
                loadRelationshipDefinitions: async (
                    params: { projectId?: number | null } = {},
                    breakpoint
                ): Promise<AccountsTableRelationshipDefinition[]> => {
                    const projectId = params.projectId ?? values.currentProjectId
                    const response = await accountRelationshipDefinitionsList(String(projectId), { pagination: 'none' })
                    breakpoint()
                    return response.results
                },
            },
        ],
    })),
    reducers({
        customPropertyCatalog: { resetDefinitionCatalogs: () => [] },
        customPropertyCatalogLoading: { resetDefinitionCatalogs: () => false },
        customPropertyCatalogProjectId: [
            null as number | null,
            {
                loadCustomPropertyDefinitions: (_, { projectId = null }) => projectId,
                loadCustomPropertyDefinitionsSuccess: (_, { payload }) => payload?.projectId ?? null,
                resetDefinitionCatalogs: () => null,
            },
        ],
        customPropertyCatalogLoaded: [
            false,
            {
                loadCustomPropertyDefinitionsSuccess: () => true,
                resetDefinitionCatalogs: () => false,
            },
        ],
        customPropertyDefinitionsError: [
            null as string | null,
            {
                loadCustomPropertyDefinitions: () => null,
                loadCustomPropertyDefinitionsFailure: (_, { error }) => error,
                resetDefinitionCatalogs: () => null,
            },
        ],
        relationshipCatalog: { resetDefinitionCatalogs: () => [] },
        relationshipCatalogLoading: { resetDefinitionCatalogs: () => false },
        relationshipCatalogProjectId: [
            null as number | null,
            {
                loadRelationshipDefinitions: (_, { projectId = null }) => projectId,
                loadRelationshipDefinitionsSuccess: (_, { payload }) => payload?.projectId ?? null,
                resetDefinitionCatalogs: () => null,
            },
        ],
        relationshipCatalogLoaded: [
            false,
            {
                loadRelationshipDefinitionsSuccess: () => true,
                resetDefinitionCatalogs: () => false,
            },
        ],
        relationshipDefinitionsError: [
            null as string | null,
            {
                loadRelationshipDefinitions: () => null,
                loadRelationshipDefinitionsFailure: (_, { error }) => error,
                resetDefinitionCatalogs: () => null,
            },
        ],
    }),
    selectors({
        customPropertyDefinitions: [
            (s) => [s.customPropertyCatalog, s.customPropertyCatalogProjectId, s.currentProjectId],
            (
                definitions: AccountsTableCustomPropertyDefinition[],
                projectId: number | null,
                currentProjectId: number | null
            ): AccountsTableCustomPropertyDefinition[] =>
                projectId === null || projectId === currentProjectId ? definitions : [],
        ],
        customPropertyDefinitionsLoaded: [
            (s) => [s.customPropertyCatalogLoaded, s.customPropertyCatalogProjectId, s.currentProjectId],
            (loaded: boolean, projectId: number | null, currentProjectId: number | null): boolean =>
                loaded && (projectId === null || projectId === currentProjectId),
        ],
        customPropertyDefinitionsLoading: [
            (s) => [s.customPropertyCatalogLoading, s.customPropertyCatalogProjectId, s.currentProjectId],
            (loading: boolean, projectId: number | null, currentProjectId: number | null): boolean =>
                loading && (projectId === null || projectId === currentProjectId),
        ],
        relationshipDefinitions: [
            (s) => [s.relationshipCatalog, s.relationshipCatalogProjectId, s.currentProjectId],
            (
                definitions: AccountsTableRelationshipDefinition[],
                projectId: number | null,
                currentProjectId: number | null
            ): AccountsTableRelationshipDefinition[] =>
                projectId === null || projectId === currentProjectId ? definitions : [],
        ],
        relationshipDefinitionsLoaded: [
            (s) => [s.relationshipCatalogLoaded, s.relationshipCatalogProjectId, s.currentProjectId],
            (loaded: boolean, projectId: number | null, currentProjectId: number | null): boolean =>
                loaded && (projectId === null || projectId === currentProjectId),
        ],
        relationshipDefinitionsLoading: [
            (s) => [s.relationshipCatalogLoading, s.relationshipCatalogProjectId, s.currentProjectId],
            (loading: boolean, projectId: number | null, currentProjectId: number | null): boolean =>
                loading && (projectId === null || projectId === currentProjectId),
        ],
        defaultSelectColumns: [
            (s) => [s.relationshipDefinitionsById],
            (definitions: Record<string, AccountsTableRelationshipDefinition>): string[] => [
                ...ACCOUNTS_DEFAULT_COLUMNS,
                ...Object.values(definitions).map((definition) => getRelationshipColumn(definition.id)),
            ],
        ],
        querySelectColumns: [
            (s) => [s.selectColumns, s.columnDisplay],
            (selectColumns: string[], columnDisplay: AccountColumnDisplayState): string[] =>
                applyColumnDisplayToSelect(selectColumns, columnDisplay),
        ],
        renderSelectColumns: [
            (s) => [s.querySelectColumns, s.tableColumnResponse, s.useDefaultColumns],
            (
                columns: string[],
                response: { requested: string[] | undefined; definitionIds: string[] } | null,
                useDefaults: boolean
            ): string[] =>
                columns.filter((column) => {
                    const id = column.match(
                        /^accounts\.(?:custom_properties(?:_history)?|relationships)\.values\.`([^`]+)`/
                    )?.[1]
                    return (
                        !id ||
                        useDefaults ||
                        !response ||
                        !objectsEqual(response.requested, columns) ||
                        response.definitionIds.includes(id)
                    )
                }),
        ],
        visibleColumnNames: [
            (s) => [s.renderSelectColumns],
            (querySelectColumns: string[]): string[] => querySelectColumns.map((c) => extractDisplayLabel(c)),
        ],
        accountsColumnGroups: [
            (s) => [s.allTablesMap, s.customPropertyDefinitions, s.relationshipDefinitions],
            (
                allTablesMap: Record<string, DatabaseSchemaTable>,
                customPropertyDefinitions: AccountsTableCustomPropertyDefinition[],
                relationshipDefinitions: AccountsTableRelationshipDefinition[]
            ): AccountColumnGroup[] =>
                buildAccountColumnGroups(allTablesMap, customPropertyDefinitions, relationshipDefinitions),
        ],
        activePickerGroup: [
            (s) => [s.accountsColumnGroups, s.pickerGroupKey],
            (accountsColumnGroups: AccountColumnGroup[], pickerGroupKey: PickerGroupKey): AccountColumnGroup | null =>
                pickerGroupKey === ALL_COLUMNS_KEY
                    ? null
                    : (accountsColumnGroups.find((group) => group.key === pickerGroupKey) ?? null),
        ],
        filteredColumnOptions: [
            (s) => [s.accountsColumnGroups, s.activePickerGroup, s.pickerSearch, s.selectColumns],
            (
                accountsColumnGroups: AccountColumnGroup[],
                activePickerGroup: AccountColumnGroup | null,
                pickerSearch: string,
                selectColumns: string[]
            ): AccountPickerColumnOption[] =>
                filterColumnOptions(accountsColumnGroups, activePickerGroup, pickerSearch, selectColumns),
        ],
        pickerSearchPlaceholder: [
            (s) => [s.activePickerGroup],
            (activePickerGroup: AccountColumnGroup | null): string =>
                activePickerGroup ? `Search ${activePickerGroup.label.toLowerCase()}` : 'Search all columns',
        ],
        customPropertyDefinitionsById: [
            (s) => [s.customPropertyDefinitions, s.tableCustomPropertyDefinitions],
            (
                catalog: AccountsTableCustomPropertyDefinition[],
                table: AccountsTableCustomPropertyDefinition[]
            ): Record<string, AccountsTableCustomPropertyDefinition> =>
                Object.fromEntries([...catalog, ...table].map((definition) => [definition.id, definition])),
        ],
        editingColumn: [
            (s) => [s.selectColumns, s.editingColumnIndex],
            (selectColumns: string[], editingColumnIndex: number | null): string | null =>
                editingColumnIndex !== null ? (selectColumns[editingColumnIndex] ?? null) : null,
        ],
        displayByAlias: [
            (s) => [s.columnDisplay],
            (columnDisplay: AccountColumnDisplayState): AccountColumnDisplayState =>
                Object.fromEntries(
                    Object.entries(columnDisplay).map(([definitionId, config]) => [
                        customPropertyAlias(definitionId),
                        config,
                    ])
                ),
        ],
        aliasToDefinition: [
            (s) => [s.customPropertyDefinitionsById],
            (
                customPropertyDefinitionsById: Record<string, AccountsTableCustomPropertyDefinition>
            ): Record<string, AccountsTableCustomPropertyDefinition> =>
                Object.fromEntries(
                    Object.values(customPropertyDefinitionsById).map((definition) => [
                        customPropertyAlias(definition.id),
                        definition,
                    ])
                ),
        ],
        relationshipDefinitionsById: [
            (s) => [s.relationshipDefinitions, s.tableRelationshipDefinitions],
            (
                catalog: AccountsTableRelationshipDefinition[],
                table: AccountsTableRelationshipDefinition[]
            ): Record<string, AccountsTableRelationshipDefinition> =>
                Object.fromEntries([...catalog, ...table].map((definition) => [definition.id, definition])),
        ],
        relationshipTaxonomicOptions: [
            (s) => [s.relationshipDefinitionsById],
            (
                relationshipDefinitionsById: Record<string, AccountsTableRelationshipDefinition>
            ): (SimpleOption & {
                id: string
                property_type: PropertyType
            })[] =>
                Object.values(relationshipDefinitionsById).map((definition) => ({
                    id: definition.id,
                    name: definition.name,
                    property_type: PropertyType.Assignee,
                })),
        ],
        customPropertyTaxonomicOptions: [
            (s) => [s.customPropertyDefinitionsById],
            (
                customPropertyDefinitionsById: Record<string, AccountsTableCustomPropertyDefinition>
            ): (SimpleOption & {
                id: string
                description?: string
                is_canonical?: boolean
                property_type: PropertyType
            })[] =>
                Object.values(customPropertyDefinitionsById).map((definition) => ({
                    id: definition.id,
                    name: definition.name,
                    description: definition.description ?? undefined,
                    is_canonical: definition.is_canonical,
                    property_type: propertyTypeForDisplayType(definition.display_type),
                })),
        ],
        aliasToRelationshipDefinition: [
            (s) => [s.relationshipDefinitionsById],
            (
                definitions: Record<string, AccountsTableRelationshipDefinition>
            ): Record<string, AccountsTableRelationshipDefinition> =>
                Object.fromEntries(
                    Object.values(definitions).map((definition) => [relationshipAlias(definition.id), definition])
                ),
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        // Seed property types so filters show valid operators.
        loadCustomPropertyDefinitionsSuccess: () => {
            updatePropertyDefinitions(
                Object.fromEntries(
                    values.customPropertyTaxonomicOptions.map((option) => [
                        `${PropertyDefinitionType.AccountCustomProperty}/${option.id}`,
                        // Filters resolve definitions by ID, not the display name.
                        { id: option.id, name: option.id, property_type: option.property_type },
                    ])
                )
            )
        },
        loadRelationshipDefinitionsSuccess: () => {
            updatePropertyDefinitions(
                Object.fromEntries(
                    values.relationshipTaxonomicOptions.map((option) => [
                        `${PropertyDefinitionType.AccountRelationship}/${option.id}`,
                        { id: option.id, name: option.id, property_type: option.property_type },
                    ])
                )
            )
        },
        [projectLogic.actionTypes.loadCurrentProjectSuccess]: ({ currentProject }) => {
            if (cache.definitionProjectId !== currentProject?.id) {
                cache.definitionProjectId = currentProject?.id
                actions.resetDefinitionCatalogs()
            }
        },
        resetColumns: () => actions.setDefaultSelectColumns(values.defaultSelectColumns),
        ensureDefinitionsLoaded: () => {
            if (!values.customPropertyDefinitionsLoaded && !values.customPropertyDefinitionsLoading) {
                actions.loadCustomPropertyDefinitions({ projectId: values.currentProjectId })
            }
            if (!values.relationshipDefinitionsLoaded && !values.relationshipDefinitionsLoading) {
                actions.loadRelationshipDefinitions({ projectId: values.currentProjectId })
            }
        },
        showColumnConfigurator: () => actions.ensureDefinitionsLoaded(),
        hydrateTableDefinitions: ({ response }) => {
            if (values.useDefaultColumns && response.columns) {
                actions.setDefaultSelectColumns([
                    ...ACCOUNTS_DEFAULT_COLUMNS,
                    ...response.columns.flatMap((column) => {
                        if (column.kind !== 'relationship') {
                            return []
                        }
                        return [getRelationshipColumn(column.definitionId)]
                    }),
                ])
            }
            updatePropertyDefinitions(
                Object.fromEntries([
                    ...values.customPropertyTaxonomicOptions.map((option) => [
                        `${PropertyDefinitionType.AccountCustomProperty}/${option.id}`,
                        { id: option.id, name: option.id, property_type: option.property_type },
                    ]),
                    ...values.relationshipTaxonomicOptions.map((option) => [
                        `${PropertyDefinitionType.AccountRelationship}/${option.id}`,
                        { id: option.id, name: option.id, property_type: option.property_type },
                    ]),
                ])
            )
        },
    })),
    afterMount(({ actions, values, cache }) => {
        cache.definitionProjectId = values.currentProjectId
        updatePropertyDefinitions(
            Object.fromEntries(
                ACCOUNT_FIELD_TAXONOMIC_OPTIONS.map((option) => [
                    `${PropertyDefinitionType.Account}/${option.id}`,
                    { id: option.id, name: option.id, property_type: option.property_type },
                ])
            )
        )
        if (!values.allTablesMap || Object.keys(values.allTablesMap).length === 0) {
            actions.loadDatabase()
        } else {
            // The picker needs fields when the SQL editor loaded only shallow schemas.
            actions.ensureAllTableFields()
        }
    }),
])
