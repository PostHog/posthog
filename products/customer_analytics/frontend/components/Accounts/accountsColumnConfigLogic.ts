import { actions, afterMount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { objectsEqual } from 'lib/utils/objects'
import { databaseTableListLogic } from 'scenes/data-management/database/databaseTableListLogic'
import { projectLogic } from 'scenes/projectLogic'
import { teamLogic } from 'scenes/teamLogic'

import { extractDisplayLabel } from '~/queries/nodes/DataTable/utils'
import { DatabaseSchemaField, DatabaseSchemaTable } from '~/queries/schema/schema-general'
import type { DataWarehouseViewLink } from '~/types'

import {
    accountRelationshipDefinitionsList,
    customPropertyDefinitionsList,
} from 'products/customer_analytics/frontend/generated/api'
import type {
    AccountRelationshipDefinitionApi,
    CustomPropertyDefinitionApi,
} from 'products/customer_analytics/frontend/generated/api.schemas'
import { joinsLogic } from 'products/data_warehouse/frontend/shared/logics/joinsLogic'

import type { accountsColumnConfigLogicType } from './accountsColumnConfigLogicType'

// Mandatory — the backend emits it as `tuple(name, external_id, id)` so the
// row identity (id) and copy-able external_id ride along with the display name.
export const ACCOUNTS_NAME_COLUMN = 'name'

// The three role columns predate relationship definitions, so saved views, shared
// URLs, and the default column set store them as bare names. They map by name onto
// the team's seeded relationship definitions and translate into the relationships
// lazy join at query-build time (`translateSelectColumns`).
export const LEGACY_ROLE_COLUMNS = {
    csm: 'CSM',
    account_executive: 'Account executive',
    account_owner: 'Account owner',
} as const

export type AccountRoleKey = keyof typeof LEGACY_ROLE_COLUMNS

export function isLegacyRoleColumn(column: string): column is AccountRoleKey {
    return column in LEGACY_ROLE_COLUMNS
}

const ACCOUNTS_HOGQL_BASE_SELECT: string[] = [
    ACCOUNTS_NAME_COLUMN,
    'accounts.tags.names AS tag_names',
    'accounts.notebooks.count AS notebook_count',
]

// Only a pre-load seed: once definitions load, pristine columns are upgraded to
// `defaultSelectColumns` so defaults aren't coupled to the legacy role names.
export const ACCOUNTS_HOGQL_DEFAULT_SELECT: string[] = [
    ...ACCOUNTS_HOGQL_BASE_SELECT,
    ...Object.keys(LEGACY_ROLE_COLUMNS),
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

export type AccountColumnGroupKey =
    | 'account_properties'
    | 'custom_properties'
    | 'relationships'
    | 'sql_expression'
    | `accounts.${string}`

// Custom property definition ids are UUIDs, which aren't valid HogQL identifiers (hyphens).
// Strip them so the column alias is a clean identifier, and so the renderer can map a visible
// column name back to its definition.
export function customPropertyAlias(id: string): string {
    return `cp_${id.replace(/-/g, '')}`
}

export function relationshipAlias(id: string): string {
    return `rel_${id.replace(/-/g, '')}`
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
    isFreeform?: boolean
}

// Field types that point at joined tables/views (lazy joins, virtual tables,
// user-defined data warehouse joins, saved queries). Each one surfaces as a
// dedicated dropdown entry in the column configurator.
const JOIN_FIELD_TYPES = new Set(['lazy_table', 'virtual_table', 'view', 'materialized_view'])

// Joins that already have a friendly, definition-driven picker group — surfacing
// their raw backing tables (account_id + a JSON blob) would just duplicate them.
const HIDDEN_JOIN_GROUPS = new Set(['custom_properties', 'relationships'])

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
    warehouseJoins: DataWarehouseViewLink[],
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
                if (HIDDEN_JOIN_GROUPS.has(field.name)) {
                    continue
                }
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
            (relationshipDefinitions: AccountRelationshipDefinitionApi[]): string[] =>
                relationshipDefinitions.length === 0
                    ? [...ACCOUNTS_HOGQL_DEFAULT_SELECT]
                    : [
                          ...ACCOUNTS_HOGQL_BASE_SELECT,
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
            (s) => [s.selectColumns, s.roleKeyToDefinition],
            (
                selectColumns: string[],
                roleKeyToDefinition: Partial<Record<AccountRoleKey, AccountRelationshipDefinitionApi>>
            ): string[] => translateSelectColumns(selectColumns, roleKeyToDefinition),
        ],
        visibleColumnNames: [
            (s) => [s.querySelectColumns],
            (querySelectColumns: string[]): string[] => querySelectColumns.map((c) => extractDisplayLabel(c)),
        ],
        accountsColumnGroups: [
            (s) => [s.allTablesMap, s.warehouseJoins, s.customPropertyDefinitions, s.relationshipDefinitions],
            (
                allTablesMap: Record<string, DatabaseSchemaTable>,
                warehouseJoins: DataWarehouseViewLink[],
                customPropertyDefinitions: CustomPropertyDefinitionApi[],
                relationshipDefinitions: AccountRelationshipDefinitionApi[]
            ): AccountColumnGroup[] =>
                buildAccountColumnGroups(
                    allTablesMap,
                    warehouseJoins,
                    customPropertyDefinitions,
                    relationshipDefinitions
                ),
        ],
        aliasToDefinition: [
            (s) => [s.customPropertyDefinitions],
            (customPropertyDefinitions: CustomPropertyDefinitionApi[]): Record<string, CustomPropertyDefinitionApi> =>
                Object.fromEntries(
                    customPropertyDefinitions.map((definition) => [customPropertyAlias(definition.id), definition])
                ),
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
    listeners(({ actions, values }) => ({
        // Customized columns (user edits, saved view, shared URL) no longer equal the
        // static default, so only pristine defaults get upgraded.
        loadRelationshipDefinitionsSuccess: () => {
            if (
                objectsEqual(values.selectColumns, ACCOUNTS_HOGQL_DEFAULT_SELECT) &&
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
        // Lazily fetch the database schema only if it isn't already in flight / loaded.
        // databaseTableListLogic dedupes concurrent calls internally.
        if (!values.allTablesMap || Object.keys(values.allTablesMap).length === 0) {
            actions.loadDatabase()
        }
        actions.loadCustomPropertyDefinitions()
        actions.loadRelationshipDefinitions()
    }),
])
