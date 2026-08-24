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

// Mandatory — the backend emits it as `tuple(name, external_id, id)` so the
// row identity (id) and copy-able external_id ride along with the display name.
export const ACCOUNTS_NAME_COLUMN = 'name'

// The three role columns predate relationship definitions, so saved views and shared
// URLs store them as bare names. They map by name onto the team's seeded relationship
// definitions and translate into the relationships lazy join at query-build time
// (`translateSelectColumns`).
export const LEGACY_ROLE_COLUMNS = {
    csm: 'CSM',
    account_executive: 'Account executive',
    account_owner: 'Account owner',
} as const

export type AccountRoleKey = keyof typeof LEGACY_ROLE_COLUMNS

export function isLegacyRoleColumn(column: string): column is AccountRoleKey {
    return column in LEGACY_ROLE_COLUMNS
}

// Pre-load seed only — `defaultSelectColumns` appends one relationship column per
// definition once the team's definitions load.
export const ACCOUNTS_DEFAULT_COLUMNS: string[] = [
    ACCOUNTS_NAME_COLUMN,
    'accounts.tags.names AS tag_names',
    'accounts.notebooks.count AS notebook_count',
]

function ensureNameColumn(columns: string[]): string[] {
    return columns.includes(ACCOUNTS_NAME_COLUMN) ? columns : [ACCOUNTS_NAME_COLUMN, ...columns]
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

// `allTablesMap` keys system tables by their fully qualified name (e.g.
// `system.accounts`), matching `resolve_visible_table_names()` on the backend.
export const ACCOUNTS_ACCOUNTS_TABLE_NAME = 'system.accounts'

export type AccountColumnGroupKey = 'account_properties' | 'custom_properties' | 'relationships' | `accounts.${string}`

export const ALL_COLUMNS_KEY = 'all'
export type PickerGroupKey = AccountColumnGroupKey | typeof ALL_COLUMNS_KEY

// Custom property definition ids are UUIDs, which aren't valid HogQL identifiers (hyphens).
// Strip them so the column alias is a clean identifier, and so the renderer can map a visible
// column name back to its definition.
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

// Keyed by custom property definition id (not alias) so the config survives column
// removal/re-add and matches how saved views key custom-property filters.
export type AccountColumnDisplayState = Record<string, AccountColumnDisplayConfig>

export const COLUMN_DISPLAY_WINDOW_OPTIONS = [7, 14, 30, 90] as const
export const DEFAULT_COLUMN_DISPLAY_WINDOW_DAYS = 7

const CUSTOM_PROPERTY_COLUMN_REGEX = /^accounts\.custom_properties\.values\.`([0-9a-fA-F-]+)` AS (cp_[0-9a-fA-F]+)$/

// Sparkline/trend columns select the write history instead of the current value. The swap
// happens at query-build time so the stored column string (saved views, shared URLs) stays
// in the stable scalar form.
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

// Legacy role names resolve through the relationships lazy join, keeping the stored
// column name (and thus saved views, URL state, and cell renderers) stable. A legacy
// role with no matching definition is dropped from the query — the definition was
// renamed or never seeded, so there is nothing to select.
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

// Null activeGroup means "All columns": search spans every non-freeform group.
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

// Field types that point at joined tables/views (lazy joins, virtual tables,
// user-defined data warehouse joins, saved queries). Each one surfaces as a
// dedicated dropdown entry in the column configurator.
const JOIN_FIELD_TYPES = new Set(['lazy_table', 'virtual_table', 'view', 'materialized_view'])

// Joins that already have a friendly, definition-driven picker group — surfacing
// their raw backing tables (account_id + a JSON blob) would just duplicate them.
const HIDDEN_JOIN_GROUPS = new Set(['custom_properties', 'relationships'])
const POSTGRES_BACKED_JOIN_GROUPS = new Set(['tags', 'notebooks'])
const POSTGRES_BACKED_ACCOUNT_FIELDS = new Set<string>(Object.values(AccountsTableAccountField))

// Field types we omit from the "Account properties" group — these are
// navigation aliases, joined tables (handled separately), or unknown types.
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
        // `accounts.<join>.<col> AS <col>` — alias keeps the visible column
        // name human-readable while disambiguating columns that collide with
        // direct fields (e.g. `name` on a joined table).
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
        // JSON dot-access through the lazy join (`events.person.properties.foo` analog), aliased to a
        // clean identifier so the alias round-trips through `visibleColumnNames` / `aliasToDefinition`.
        expression: `accounts.custom_properties.values.\`${definition.id}\` AS ${customPropertyAlias(definition.id)}`,
    }))
}

// Seeded definitions keep their legacy bare name as the picker expression so selecting
// them dedupes against the default columns; other definitions get a rel_ alias.
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
        // Every join under `system.accounts` carries the `accounts.` prefix
        // — drop it from the user-facing label since it's just visual noise.
        joinGroups.push({ key, label: fieldName, options })
    }

    if (accountsTable) {
        for (const field of Object.values(accountsTable.fields)) {
            if (JOIN_FIELD_TYPES.has(field.type)) {
                if (HIDDEN_JOIN_GROUPS.has(field.name) || !POSTGRES_BACKED_JOIN_GROUPS.has(field.name)) {
                    continue
                }
                const joinedTable = field.table ? allTablesMap?.[field.table] : undefined
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

    // Omit definition-driven groups entirely when the team has no definitions, so the
    // category dropdown doesn't show empty entries.
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
    relationshipDefinitionsLoaded: boolean
    relationshipDefinitionsLoading: boolean
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
        // Keep propertyDefinitionsModel mounted so the seeded custom-property definitions
        // (see loadCustomPropertyDefinitionsSuccess) survive until the filter UI reads them.
        logic: [propertyDefinitionsModel],
    })),
    actions({
        setSelectColumns: (columns: string[]) => ({ columns }),
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
                setSelectColumns: (_, { columns }) => ensureNameColumn(columns),
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
        // Which visible-column row the configurator's edit section targets. Any action that
        // reshuffles or replaces the column list closes the editor so the index can't go stale.
        editingColumnIndex: [
            null as number | null,
            {
                setEditingColumnIndex: (_, { index }) => index,
                setSelectColumns: () => null,
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
                // A stale query from another category would silently hide results.
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
        // Queries wait for this so the list fetches once with its final columns,
        // instead of fetching with the base columns and refetching after the
        // definitions land (a wasted query and a visible column pop).
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
        // Seeded definitions keep their legacy bare name so existing saved views and
        // shared URLs dedupe against them.
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
        // What the AccountsQuery actually selects: `selectColumns` with legacy role
        // names resolved through the relationships lazy join (or dropped when the
        // matching definition doesn't exist). Row cells align to THIS list.
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
        // Re-keyed by the cp_<id> column alias so cell renderers can look up their
        // display mode by visible column name.
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
        // The same map re-keyed by the cp_<id> column alias — resolves visible column
        // names back to their definition (table header, configurator labels).
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
        // Items for the custom-properties taxonomic group (fed via `optionsFromProp`): the
        // definition id is the stable filter key, the name is what's displayed and searched.
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
        // Resolves a visible column name (legacy role key or rel_ alias) back to its
        // relationship definition — drives the cell renderer and header label.
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
    listeners(({ actions, values, selectors }) => ({
        // Seed the shared propertyDefinitionsModel so OperatorValueSelect resolves each
        // custom property's type (numeric/boolean/datetime/string) to the right operator set.
        loadCustomPropertyDefinitionsSuccess: () => {
            updatePropertyDefinitions(
                Object.fromEntries(
                    values.customPropertyTaxonomicOptions.map((option) => [
                        `${PropertyDefinitionType.AccountCustomProperty}/${option.id}`,
                        // name is the id, not the display name: OperatorValueSelect resolves
                        // the definition by matching `name` against the filter key (the id).
                        { id: option.id, name: option.id, property_type: option.property_type },
                    ])
                )
            )
        },
        // Customized columns (user edits, saved view, shared URL) no longer equal the
        // default they diverged from, so only still-default columns get upgraded.
        loadRelationshipDefinitionsSuccess: (_, __, ___, previousState) => {
            const previousDefault = selectors.defaultSelectColumns(previousState)
            if (
                objectsEqual(values.selectColumns, previousDefault) &&
                !objectsEqual(values.defaultSelectColumns, values.selectColumns)
            ) {
                actions.setSelectColumns(values.defaultSelectColumns)
            }
        },
        resetColumns: () => {
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
        // Lazily fetch the database schema only if it isn't already in flight / loaded.
        // databaseTableListLogic dedupes concurrent calls internally.
        if (!values.allTablesMap || Object.keys(values.allTablesMap).length === 0) {
            actions.loadDatabase()
        } else {
            // The store may hold a shallow (fields-less) schema left by the SQL editor; the
            // column picker needs every table's fields.
            actions.ensureAllTableFields()
        }
        actions.loadCustomPropertyDefinitions()
        actions.loadRelationshipDefinitions()
    }),
])
