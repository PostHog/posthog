import { MakeLogicType, actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import type { SimpleOption } from 'lib/components/TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils/objects'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { propertyDefinitionsModel, updatePropertyDefinitions } from '~/models/propertyDefinitionsModel'
import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'
import { AccountsTableAccountField, DatabaseSchemaField, DatabaseSchemaTable } from '~/queries/schema/schema-general'
import { PropertyDefinitionType, PropertyType } from '~/types'

import {
    accountRelationshipDefinitionsList,
    customPropertyDefinitionsList,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountRelationshipDefinitionApi,
    CustomPropertyDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'

import { ACCOUNT_FIELD_TAXONOMIC_OPTIONS, propertyTypeForDisplayType } from './accountsPropertyFilters'

export const ACCOUNTS_NAME_COLUMN = 'name'
export const ACCOUNTS_TAGS_COLUMN = 'accounts.tags.names AS tag_names'
const LEGACY_ACCOUNTS_TAGS_NAME_COLUMN = 'accounts.tags.names AS names'
const LEGACY_ACCOUNTS_TAGS_ACCOUNT_ID_COLUMN = 'accounts.tags.account_id AS account_id'

// Legacy role names remain serialized for saved views and shared URLs.
// Query planning maps them to seeded relationship definitions.
export const LEGACY_ROLE_COLUMNS = {
    csm: 'CSM',
    account_executive: 'Account executive',
    account_owner: 'Account owner',
} as const

export type AccountRoleKey = keyof typeof LEGACY_ROLE_COLUMNS

export function isLegacyRoleColumn(column: string): column is AccountRoleKey {
    return column in LEGACY_ROLE_COLUMNS
}

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

// Keep stored column strings scalar so saved views and shared URLs stay stable.
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

function relationshipExpression(definition: AccountRelationshipDefinitionApi, alias: string): string {
    return `accounts.relationships.values.\`${definition.id}\` AS ${alias}`
}

export const ROLE_KEY_BY_NAME: Record<string, AccountRoleKey> = Object.fromEntries(
    Object.entries(LEGACY_ROLE_COLUMNS).map(([key, name]) => [name, key as AccountRoleKey])
)

export function roleKeyToDefinitionMap(
    definitions: AccountRelationshipDefinitionApi[]
): Partial<Record<AccountRoleKey, AccountRelationshipDefinitionApi>> {
    return Object.fromEntries(
        definitions
            .filter((definition) => ROLE_KEY_BY_NAME[definition.name])
            .map((definition) => [ROLE_KEY_BY_NAME[definition.name], definition])
    )
}

// Keep legacy role names stable in persisted state. Omit roles without a matching definition.
export function translateSelectColumns(
    columns: string[],
    roleKeyToDefinition: Partial<Record<AccountRoleKey, AccountRelationshipDefinitionApi>>
): string[] {
    return columns.flatMap((column) => {
        if (!isLegacyRoleColumn(column)) {
            return [column]
        }
        const definition = roleKeyToDefinition[column]
        return definition ? [relationshipExpression(definition, column)] : []
    })
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

function customPropertyOptions(definitions: CustomPropertyDefinitionApi[]): AccountColumnOption[] {
    return definitions.map((definition) => ({
        name: definition.name,
        type: definition.display_type,
        expression: `accounts.custom_properties.values.\`${definition.id}\` AS ${customPropertyAlias(definition.id)}`,
    }))
}

// Keep seeded role names compatible with default columns and persisted selections.
function relationshipOptions(definitions: AccountRelationshipDefinitionApi[]): AccountColumnOption[] {
    return definitions.map((definition) => ({
        name: definition.name,
        expression:
            ROLE_KEY_BY_NAME[definition.name] ?? relationshipExpression(definition, relationshipAlias(definition.id)),
    }))
}

export function buildAccountColumnGroups(
    allTablesMap: Record<string, DatabaseSchemaTable> | null | undefined,
    customPropertyDefinitions: CustomPropertyDefinitionApi[] = [],
    relationshipDefinitions: AccountRelationshipDefinitionApi[] = []
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
    aliasToDefinition: Record<string, CustomPropertyDefinitionApi>
    aliasToRelationshipDefinition: Record<string, AccountRelationshipDefinitionApi>
    columnConfiguratorVisible: boolean
    columnDisplay: AccountColumnDisplayState
    customPropertyDefinitions: CustomPropertyDefinitionApi[]
    customPropertyDefinitionsById: Record<string, CustomPropertyDefinitionApi>
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
    relationshipDefinitions: AccountRelationshipDefinitionApi[]
    relationshipDefinitionsById: Record<string, AccountRelationshipDefinitionApi>
    relationshipDefinitionsLoaded: boolean
    relationshipDefinitionsLoading: boolean
    relationshipTaxonomicOptions: (SimpleOption & {
        id: string
        property_type: PropertyType
    })[]
    roleKeyToDefinition: Partial<Record<AccountRoleKey, AccountRelationshipDefinitionApi>>
    selectColumns: string[]
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
    hideColumnConfigurator: () => {
        value: true
    }
    loadCustomPropertyDefinitions: () => any
    loadCustomPropertyDefinitionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadCustomPropertyDefinitionsSuccess: (
        customPropertyDefinitions: CustomPropertyDefinitionApi[],
        payload?: any
    ) => {
        customPropertyDefinitions: CustomPropertyDefinitionApi[]
        payload?: any
    }
    loadRelationshipDefinitions: () => any
    loadRelationshipDefinitionsFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadRelationshipDefinitionsSuccess: (
        relationshipDefinitions: AccountRelationshipDefinitionApi[],
        payload?: any
    ) => {
        relationshipDefinitions: AccountRelationshipDefinitionApi[]
        payload?: any
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
        defaultSelectColumns: (relationshipDefinitions: AccountRelationshipDefinitionApi[]) => string[]
        roleKeyToDefinition: (
            relationshipDefinitions: AccountRelationshipDefinitionApi[]
        ) => Partial<Record<AccountRoleKey, AccountRelationshipDefinitionApi>>
        querySelectColumns: (
            selectColumns: string[],
            roleKeyToDefinition: Partial<
                Record<'account_executive' | 'account_owner' | 'csm', AccountRelationshipDefinitionApi>
            >,
            columnDisplay: AccountColumnDisplayState
        ) => string[]
        visibleColumnNames: (querySelectColumns: string[]) => string[]
        accountsColumnGroups: (
            allTablesMap: Record<string, DatabaseSchemaTable>,
            customPropertyDefinitions: CustomPropertyDefinitionApi[],
            relationshipDefinitions: AccountRelationshipDefinitionApi[]
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
            customPropertyDefinitions: CustomPropertyDefinitionApi[]
        ) => Record<string, CustomPropertyDefinitionApi>
        editingColumn: (selectColumns: string[], editingColumnIndex: number | null) => string | null
        displayByAlias: (columnDisplay: AccountColumnDisplayState) => AccountColumnDisplayState
        aliasToDefinition: (
            customPropertyDefinitionsById: Record<string, CustomPropertyDefinitionApi>
        ) => Record<string, CustomPropertyDefinitionApi>
        relationshipDefinitionsById: (
            relationshipDefinitions: AccountRelationshipDefinitionApi[]
        ) => Record<string, AccountRelationshipDefinitionApi>
        relationshipTaxonomicOptions: (relationshipDefinitions: AccountRelationshipDefinitionApi[]) => (SimpleOption & {
            id: string
            property_type: PropertyType
        })[]
        customPropertyTaxonomicOptions: (customPropertyDefinitions: CustomPropertyDefinitionApi[]) => (SimpleOption & {
            description?: string
            id: string
            is_canonical?: boolean
            property_type: PropertyType
        })[]
        aliasToRelationshipDefinition: (
            relationshipDefinitions: AccountRelationshipDefinitionApi[],
            roleKeyToDefinition: Partial<
                Record<'account_executive' | 'account_owner' | 'csm', AccountRelationshipDefinitionApi>
            >
        ) => Record<string, AccountRelationshipDefinitionApi>
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
        // Wait for definitions to avoid a second query and visible column changes.
        relationshipDefinitionsLoaded: [
            false,
            {
                loadRelationshipDefinitionsSuccess: () => true,
                loadRelationshipDefinitionsFailure: () => true,
            },
        ],
    }),
    loaders(({ values }) => ({
        customPropertyDefinitions: [
            [] as CustomPropertyDefinitionApi[],
            {
                loadCustomPropertyDefinitions: async (): Promise<CustomPropertyDefinitionApi[]> => {
                    const response = await customPropertyDefinitionsList(String(values.currentProjectId))
                    return response.results
                },
            },
        ],
        relationshipDefinitions: [
            [] as AccountRelationshipDefinitionApi[],
            {
                loadRelationshipDefinitions: async (): Promise<AccountRelationshipDefinitionApi[]> => {
                    const response = await accountRelationshipDefinitionsList(String(values.currentProjectId))
                    return response.results
                },
            },
        ],
    })),
    selectors({
        // Keep legacy names so defaults dedupe persisted selections.
        defaultSelectColumns: [
            (s) => [s.relationshipDefinitions],
            (relationshipDefinitions: AccountRelationshipDefinitionApi[]): string[] => [
                ...ACCOUNTS_DEFAULT_COLUMNS,
                ...relationshipDefinitions.map(
                    (definition) =>
                        ROLE_KEY_BY_NAME[definition.name] ??
                        relationshipExpression(definition, relationshipAlias(definition.id))
                ),
            ],
        ],
        roleKeyToDefinition: [
            (s) => [s.relationshipDefinitions],
            (
                relationshipDefinitions: AccountRelationshipDefinitionApi[]
            ): Partial<Record<AccountRoleKey, AccountRelationshipDefinitionApi>> =>
                roleKeyToDefinitionMap(relationshipDefinitions),
        ],
        querySelectColumns: [
            (s) => [s.selectColumns, s.roleKeyToDefinition, s.columnDisplay],
            (
                selectColumns: string[],
                roleKeyToDefinition: Partial<Record<AccountRoleKey, AccountRelationshipDefinitionApi>>,
                columnDisplay: AccountColumnDisplayState
            ): string[] =>
                applyColumnDisplayToSelect(translateSelectColumns(selectColumns, roleKeyToDefinition), columnDisplay),
        ],
        visibleColumnNames: [
            (s) => [s.querySelectColumns],
            (querySelectColumns: string[]): string[] => querySelectColumns.map((c) => extractDisplayLabel(c)),
        ],
        accountsColumnGroups: [
            (s) => [s.allTablesMap, s.customPropertyDefinitions, s.relationshipDefinitions],
            (
                allTablesMap: Record<string, DatabaseSchemaTable>,
                customPropertyDefinitions: CustomPropertyDefinitionApi[],
                relationshipDefinitions: AccountRelationshipDefinitionApi[]
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
            (s) => [s.customPropertyDefinitions],
            (customPropertyDefinitions: CustomPropertyDefinitionApi[]): Record<string, CustomPropertyDefinitionApi> =>
                Object.fromEntries(customPropertyDefinitions.map((definition) => [definition.id, definition])),
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
                customPropertyDefinitionsById: Record<string, CustomPropertyDefinitionApi>
            ): Record<string, CustomPropertyDefinitionApi> =>
                Object.fromEntries(
                    Object.values(customPropertyDefinitionsById).map((definition) => [
                        customPropertyAlias(definition.id),
                        definition,
                    ])
                ),
        ],
        relationshipDefinitionsById: [
            (s) => [s.relationshipDefinitions],
            (
                relationshipDefinitions: AccountRelationshipDefinitionApi[]
            ): Record<string, AccountRelationshipDefinitionApi> =>
                Object.fromEntries(relationshipDefinitions.map((definition) => [definition.id, definition])),
        ],
        relationshipTaxonomicOptions: [
            (s) => [s.relationshipDefinitions],
            (
                relationshipDefinitions: AccountRelationshipDefinitionApi[]
            ): (SimpleOption & {
                id: string
                property_type: PropertyType
            })[] =>
                relationshipDefinitions.map((definition) => ({
                    id: definition.id,
                    name: definition.name,
                    property_type: PropertyType.Assignee,
                })),
        ],
        customPropertyTaxonomicOptions: [
            (s) => [s.customPropertyDefinitions],
            (
                customPropertyDefinitions: CustomPropertyDefinitionApi[]
            ): (SimpleOption & {
                id: string
                description?: string
                is_canonical?: boolean
                property_type: PropertyType
            })[] =>
                customPropertyDefinitions.map((definition) => ({
                    id: definition.id,
                    name: definition.name,
                    description: definition.description ?? undefined,
                    is_canonical: definition.is_canonical,
                    property_type: propertyTypeForDisplayType(definition.display_type),
                })),
        ],
        aliasToRelationshipDefinition: [
            (s) => [s.relationshipDefinitions, s.roleKeyToDefinition],
            (
                relationshipDefinitions: AccountRelationshipDefinitionApi[],
                roleKeyToDefinition: Partial<Record<AccountRoleKey, AccountRelationshipDefinitionApi>>
            ): Record<string, AccountRelationshipDefinitionApi> => ({
                ...Object.fromEntries(
                    relationshipDefinitions.map((definition) => [relationshipAlias(definition.id), definition])
                ),
                ...roleKeyToDefinition,
            }),
        ],
    }),
    listeners(({ actions, values, selectors, cache }) => ({
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
        restoreSelectColumns: () => {
            cache.hasRestoredColumns = true
        },
        // Only upgrade unchanged defaults. Never replace restored selections.
        loadRelationshipDefinitionsSuccess: (_, __, ___, previousState) => {
            updatePropertyDefinitions(
                Object.fromEntries(
                    values.relationshipTaxonomicOptions.map((option) => [
                        `${PropertyDefinitionType.AccountRelationship}/${option.id}`,
                        { id: option.id, name: option.id, property_type: option.property_type },
                    ])
                )
            )
            const previousDefault = selectors.defaultSelectColumns(previousState)
            if (
                !cache.hasRestoredColumns &&
                objectsEqual(values.selectColumns, previousDefault) &&
                !objectsEqual(values.defaultSelectColumns, values.selectColumns)
            ) {
                actions.setDefaultSelectColumns(values.defaultSelectColumns)
            }
        },
        resetColumns: () => {
            cache.hasRestoredColumns = false
            if (!objectsEqual(values.selectColumns, values.defaultSelectColumns)) {
                actions.setSelectColumns(values.defaultSelectColumns)
            }
        },
    })),
    afterMount(({ actions, values }) => {
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
        actions.loadCustomPropertyDefinitions()
        actions.loadRelationshipDefinitions()
    }),
])
