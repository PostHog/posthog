import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import type { SimpleOption } from 'lib/components/TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils/objects'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { propertyDefinitionsModel, updatePropertyDefinitions } from '~/models/propertyDefinitionsModel'
import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'
import { DatabaseSchemaField, DatabaseSchemaTable } from '~/queries/schema/schema-general'
import { PropertyDefinitionType, PropertyType } from '~/types'
import type { DataWarehouseViewLink } from '~/types'

import { customPropertyDefinitionsList } from 'products/customer_analytics/frontend/generated/api'
import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'
import { joinsLogic } from 'products/data_warehouse/frontend/shared/logics/joinsLogic'

import type { accountsColumnConfigLogicType } from './accountsColumnConfigLogicType'
import { propertyTypeForDisplayType } from './accountsCustomPropertyFilters'

// Mandatory — the backend emits it as `tuple(name, external_id, id)` so the
// row identity (id) and copy-able external_id ride along with the display name.
export const ACCOUNTS_NAME_COLUMN = 'name'

export const ACCOUNTS_HOGQL_DEFAULT_SELECT: string[] = [
    ACCOUNTS_NAME_COLUMN,
    'accounts.tags.names AS tag_names',
    'accounts.notebooks.count AS notebook_count',
    'csm',
    'account_executive',
    'account_owner',
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

// The data-warehouse-join API normalizes source_table_name via
// `table.to_printed_hogql()` which, for system PostgresTables, returns the
// unqualified name. Compare against both forms so we catch joins regardless
// of which name the backend hands us.
const ACCOUNTS_JOIN_SOURCE_TABLE_NAMES = new Set(['accounts', ACCOUNTS_ACCOUNTS_TABLE_NAME])

export type AccountColumnGroupKey = 'account_properties' | 'custom_properties' | 'sql_expression' | `accounts.${string}`

// Custom property definition ids are UUIDs, which aren't valid HogQL identifiers (hyphens).
// Strip them so the column alias is a clean identifier, and so the renderer can map a visible
// column name back to its definition.
export function customPropertyAlias(id: string): string {
    return `cp_${id.replace(/-/g, '')}`
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
    isFreeform?: boolean
}

// Field types that point at joined tables/views (lazy joins, virtual tables,
// user-defined data warehouse joins, saved queries). Each one surfaces as a
// dedicated dropdown entry in the column configurator.
const JOIN_FIELD_TYPES = new Set(['lazy_table', 'virtual_table', 'view', 'materialized_view'])

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

export function buildAccountColumnGroups(
    allTablesMap: Record<string, DatabaseSchemaTable> | null | undefined,
    warehouseJoins: DataWarehouseViewLink[],
    customPropertyDefinitions: CustomPropertyDefinitionApi[] = []
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
                const joinedTable = field.table ? allTablesMap?.[field.table] : undefined
                addJoinGroup(field.name, joinOptionsFromSchema(field, joinedTable))
                continue
            }
            if (SKIPPED_DIRECT_FIELD_TYPES.has(field.type)) {
                continue
            }
            directOptions.push({
                name: field.name,
                expression: field.hogql_value || field.name,
                type: field.type,
            })
        }
    }

    // Data-warehouse joins targeting `system.accounts` are returned in the
    // separate `joins` array on the schema response (loaded by `joinsLogic`),
    // not inside the source table's `fields`. Surface them as additional
    // first-class column groups so users don't have to drop to SQL.
    for (const join of warehouseJoins) {
        if (
            !join.source_table_name ||
            !ACCOUNTS_JOIN_SOURCE_TABLE_NAMES.has(join.source_table_name) ||
            !join.field_name ||
            !join.joining_table_name
        ) {
            continue
        }
        const joinedTable = allTablesMap?.[join.joining_table_name]
        if (!joinedTable) {
            continue
        }
        const columnNames = Object.keys(joinedTable.fields)
        addJoinGroup(join.field_name, buildJoinOptions(join.field_name, columnNames, joinedTable))
    }

    // Omit the group entirely when the team has no definitions, so the category dropdown
    // doesn't show an empty "Custom properties" entry.
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

    return [
        { key: 'account_properties', label: 'Account properties', options: directOptions },
        ...customPropertyGroups,
        ...joinGroups,
        { key: 'sql_expression', label: 'SQL expression', options: [], isFreeform: true },
    ]
}

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
            joinsLogic,
            ['joins as warehouseJoins', 'joinsLoading as warehouseJoinsLoading'],
        ],
        actions: [databaseTableListLogic, ['loadDatabase'], joinsLogic, ['loadJoins']],
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
    }),
    reducers({
        selectColumns: [
            [...ACCOUNTS_HOGQL_DEFAULT_SELECT],
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
                resetColumns: () => [...ACCOUNTS_HOGQL_DEFAULT_SELECT],
            },
        ],
        columnConfiguratorVisible: [
            false,
            {
                showColumnConfigurator: () => true,
                hideColumnConfigurator: () => false,
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
    })),
    selectors({
        visibleColumnNames: [
            (s) => [s.selectColumns],
            (selectColumns: string[]): string[] => selectColumns.map((c) => extractDisplayLabel(c)),
        ],
        accountsColumnGroups: [
            (s) => [s.allTablesMap, s.warehouseJoins, s.customPropertyDefinitions],
            (
                allTablesMap: Record<string, DatabaseSchemaTable>,
                warehouseJoins: DataWarehouseViewLink[],
                customPropertyDefinitions: CustomPropertyDefinitionApi[]
            ): AccountColumnGroup[] =>
                buildAccountColumnGroups(allTablesMap, warehouseJoins, customPropertyDefinitions),
        ],
        aliasToDefinition: [
            (s) => [s.customPropertyDefinitions],
            (customPropertyDefinitions: CustomPropertyDefinitionApi[]): Record<string, CustomPropertyDefinitionApi> =>
                Object.fromEntries(
                    customPropertyDefinitions.map((definition) => [customPropertyAlias(definition.id), definition])
                ),
        ],
        customPropertyDefinitionsById: [
            (s) => [s.customPropertyDefinitions],
            (customPropertyDefinitions: CustomPropertyDefinitionApi[]): Record<string, CustomPropertyDefinitionApi> =>
                Object.fromEntries(customPropertyDefinitions.map((definition) => [definition.id, definition])),
        ],
        // Items for the custom-properties taxonomic group (fed via `optionsFromProp`): the
        // definition id is the stable filter key, the name is what's displayed and searched.
        customPropertyTaxonomicOptions: [
            (s) => [s.customPropertyDefinitions],
            (
                customPropertyDefinitions: CustomPropertyDefinitionApi[]
            ): (SimpleOption & { id: string; property_type: PropertyType })[] =>
                customPropertyDefinitions.map((definition) => ({
                    id: definition.id,
                    name: definition.name,
                    property_type: propertyTypeForDisplayType(definition.display_type),
                })),
        ],
    }),
    listeners(() => ({
        // Seed the shared propertyDefinitionsModel so OperatorValueSelect resolves each
        // custom property's type (numeric/boolean/datetime/string) to the right operator set.
        loadCustomPropertyDefinitionsSuccess: ({ customPropertyDefinitions }) => {
            updatePropertyDefinitions(
                Object.fromEntries(
                    customPropertyDefinitions.map((definition) => [
                        `${PropertyDefinitionType.AccountCustomProperty}/${definition.id}`,
                        {
                            id: definition.id,
                            name: definition.id,
                            property_type: propertyTypeForDisplayType(definition.display_type),
                        },
                    ])
                )
            )
        },
    })),
    afterMount(({ actions, values }) => {
        // Lazily fetch the database schema only if it isn't already in flight / loaded.
        // databaseTableListLogic dedupes concurrent calls internally.
        if (!values.allTablesMap || Object.keys(values.allTablesMap).length === 0) {
            actions.loadDatabase()
        }
        actions.loadCustomPropertyDefinitions()
    }),
])
