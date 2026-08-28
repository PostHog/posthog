import { isUUIDLike } from 'lib/utils/guards'

import {
    AccountsTableAccountField,
    AccountsTableAccountFieldFilter,
    AccountsTableAccountFieldOperator,
    AccountsTableAccountIdFilter,
    AccountsTableAssignedToFilter,
    AccountsTableColumn,
    AccountsTableCustomPropertyFilter,
    AccountsTableCustomPropertyOperator,
    AccountsTableFilter,
    AccountsTableQuery,
    AccountsTableRow,
    AccountsTableSort,
    AccountsTableSortDirection,
    AccountsTableSortableColumn,
    AccountsTableTagsFilter,
    AccountsTableUnassignedFilter,
    NodeKind,
} from '~/queries/schema/schema-general'
import { AccountCustomPropertyFilter, PropertyOperator, PropertyType } from '~/types'

import type { CustomPropertyDefinitionApi } from 'products/customer_analytics/frontend/generated/api.schemas'

import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from '../../constants'
import { isNumericDisplayType } from '../../scenes/CustomerAnalyticsConfigurationScene/account/customPropertyTypes'
import type { AccountColumnDisplayState } from './accountsColumnConfigLogic'
import type { AccountSortOrder, RoleFilterValue } from './accountsLogic'
import type { TileFilter } from './accountsOverviewTilesLogic'
import { ACCOUNT_FIELD_PROPERTY_TYPES, AccountFilter, isAccountPropertyFilter } from './accountsPropertyFilters'

const RELATIONSHIP_COLUMN_REGEX = /^accounts\.relationships\.values\.`([0-9a-fA-F-]+)` AS [A-Za-z_][\w]*$/
const CUSTOM_PROPERTY_COLUMN_REGEX = /^accounts\.custom_properties\.values\.`([0-9a-fA-F-]+)` AS [A-Za-z_][\w]*$/
const CUSTOM_PROPERTY_HISTORY_COLUMN_REGEX =
    /^accounts\.custom_properties_history\.values\.`([0-9a-fA-F-]+)` AS [A-Za-z_][\w]*$/
const JSON_ACCOUNT_FIELD_REGEX = /^JSONExtractString\((?:accounts\.)?properties,\s*['"`]([A-Za-z_][\w]*)['"`]\)$/

const ACCOUNT_FIELD_VALUES = new Set<string>(Object.values(AccountsTableAccountField))

const ACCOUNT_FIELD_OPERATOR_MAP: Partial<Record<PropertyOperator, AccountsTableAccountFieldOperator>> = {
    [PropertyOperator.Exact]: AccountsTableAccountFieldOperator.Exact,
    [PropertyOperator.IsNot]: AccountsTableAccountFieldOperator.IsNot,
    [PropertyOperator.IContains]: AccountsTableAccountFieldOperator.Contains,
    [PropertyOperator.NotIContains]: AccountsTableAccountFieldOperator.DoesNotContain,
    [PropertyOperator.IsSet]: AccountsTableAccountFieldOperator.IsSet,
    [PropertyOperator.IsNotSet]: AccountsTableAccountFieldOperator.IsNotSet,
    [PropertyOperator.IsDateExact]: AccountsTableAccountFieldOperator.DateExact,
    [PropertyOperator.IsDateBefore]: AccountsTableAccountFieldOperator.DateBefore,
    [PropertyOperator.IsDateAfter]: AccountsTableAccountFieldOperator.DateAfter,
}

const ACCOUNT_FIELD_TEXT_OPERATORS = new Set<AccountsTableAccountFieldOperator>([
    AccountsTableAccountFieldOperator.Exact,
    AccountsTableAccountFieldOperator.IsNot,
    AccountsTableAccountFieldOperator.Contains,
    AccountsTableAccountFieldOperator.DoesNotContain,
    AccountsTableAccountFieldOperator.IsSet,
    AccountsTableAccountFieldOperator.IsNotSet,
])
const ACCOUNT_FIELD_DATE_OPERATORS = new Set<AccountsTableAccountFieldOperator>([
    AccountsTableAccountFieldOperator.DateExact,
    AccountsTableAccountFieldOperator.DateBefore,
    AccountsTableAccountFieldOperator.DateAfter,
    AccountsTableAccountFieldOperator.IsSet,
    AccountsTableAccountFieldOperator.IsNotSet,
])

const CUSTOM_PROPERTY_OPERATOR_MAP: Partial<Record<PropertyOperator, AccountsTableCustomPropertyOperator>> = {
    [PropertyOperator.Exact]: AccountsTableCustomPropertyOperator.Exact,
    [PropertyOperator.IsNot]: AccountsTableCustomPropertyOperator.IsNot,
    [PropertyOperator.IContains]: AccountsTableCustomPropertyOperator.Contains,
    [PropertyOperator.NotIContains]: AccountsTableCustomPropertyOperator.DoesNotContain,
    [PropertyOperator.GreaterThan]: AccountsTableCustomPropertyOperator.GreaterThan,
    [PropertyOperator.GreaterThanOrEqual]: AccountsTableCustomPropertyOperator.GreaterThanOrEqual,
    [PropertyOperator.LessThan]: AccountsTableCustomPropertyOperator.LessThan,
    [PropertyOperator.LessThanOrEqual]: AccountsTableCustomPropertyOperator.LessThanOrEqual,
    [PropertyOperator.IsSet]: AccountsTableCustomPropertyOperator.IsSet,
    [PropertyOperator.IsNotSet]: AccountsTableCustomPropertyOperator.IsNotSet,
    [PropertyOperator.IsDateExact]: AccountsTableCustomPropertyOperator.DateExact,
    [PropertyOperator.IsDateBefore]: AccountsTableCustomPropertyOperator.DateBefore,
    [PropertyOperator.IsDateAfter]: AccountsTableCustomPropertyOperator.DateAfter,
}

export interface AccountsTablePlannedColumn {
    visibleName: string
    column: AccountsTableColumn
}

export interface AccountsTableQueryPlan {
    query: AccountsTableQuery
    columns: AccountsTablePlannedColumn[]
}

export interface BuildAccountsTableQueryPlanInput {
    querySelectColumns: string[]
    visibleColumnNames: string[]
    searchQuery: string
    tagsFilter: string[]
    allRolesUnassigned: boolean
    assignedToFilter: RoleFilterValue
    accountIdFilter: string | null
    tileFilter: TileFilter | null
    accountFilters: AccountFilter[]
    customPropertyDefinitionsById: Record<string, CustomPropertyDefinitionApi>
    columnDisplay: AccountColumnDisplayState
    sortOrder: AccountSortOrder
    canSortClientSide: boolean
}

function accountFieldFromExpression(expression: string): AccountsTableAccountField | null {
    const normalized = expression.trim().replace(/^accounts\./, '')
    if (ACCOUNT_FIELD_VALUES.has(normalized)) {
        return normalized as AccountsTableAccountField
    }
    const jsonField = expression.trim().match(JSON_ACCOUNT_FIELD_REGEX)?.[1]
    return jsonField && ACCOUNT_FIELD_VALUES.has(jsonField) ? (jsonField as AccountsTableAccountField) : null
}

export function columnFromExpression(
    expression: string,
    columnDisplay: AccountColumnDisplayState
): AccountsTableColumn | null {
    if (expression === 'accounts.tags.names AS tag_names') {
        return { kind: 'tags' }
    }
    if (expression === 'accounts.notebooks.count AS notebook_count') {
        return { kind: 'note_count' }
    }

    const relationshipDefinitionId = expression.match(RELATIONSHIP_COLUMN_REGEX)?.[1]
    if (relationshipDefinitionId && isUUIDLike(relationshipDefinitionId)) {
        return { kind: 'relationship', definitionId: relationshipDefinitionId }
    }
    const customPropertyDefinitionId = expression.match(CUSTOM_PROPERTY_COLUMN_REGEX)?.[1]
    if (customPropertyDefinitionId && isUUIDLike(customPropertyDefinitionId)) {
        return { kind: 'custom_property', definitionId: customPropertyDefinitionId }
    }
    const customPropertyHistoryDefinitionId = expression.match(CUSTOM_PROPERTY_HISTORY_COLUMN_REGEX)?.[1]
    if (customPropertyHistoryDefinitionId && isUUIDLike(customPropertyHistoryDefinitionId)) {
        const windowDays = columnDisplay[customPropertyHistoryDefinitionId]?.window_days
        if (windowDays !== 7 && windowDays !== 14 && windowDays !== 30 && windowDays !== 90) {
            return null
        }
        return {
            kind: 'custom_property_history',
            definitionId: customPropertyHistoryDefinitionId,
            windowDays,
        }
    }
    const accountField = accountFieldFromExpression(expression)
    return accountField ? { kind: 'account_field', field: accountField } : null
}

function accountFieldFilter(filter: AccountFilter): AccountsTableAccountFieldFilter | null {
    if (!isAccountPropertyFilter(filter) || !ACCOUNT_FIELD_VALUES.has(filter.key)) {
        return null
    }
    const field = filter.key as AccountsTableAccountField
    const propertyType = ACCOUNT_FIELD_PROPERTY_TYPES[field]
    const operator = ACCOUNT_FIELD_OPERATOR_MAP[filter.operator]
    if (!operator) {
        return null
    }
    if (
        (propertyType === PropertyType.String && !ACCOUNT_FIELD_TEXT_OPERATORS.has(operator)) ||
        (propertyType === PropertyType.DateTime && !ACCOUNT_FIELD_DATE_OPERATORS.has(operator))
    ) {
        return null
    }
    const rawValues = Array.isArray(filter.value) ? filter.value : filter.value == null ? [] : [filter.value]
    const values = rawValues.filter((value): value is string => typeof value === 'string')
    const doesNotNeedValues =
        operator === AccountsTableAccountFieldOperator.IsSet || operator === AccountsTableAccountFieldOperator.IsNotSet
    if (!doesNotNeedValues && values.length === 0) {
        return null
    }
    return { kind: 'account_field', field, operator, values }
}

function customPropertyFilter(
    filter: AccountCustomPropertyFilter,
    definitionsById: Record<string, CustomPropertyDefinitionApi>
): AccountsTableCustomPropertyFilter | null {
    if (!filter.key || !isUUIDLike(filter.key)) {
        return null
    }
    const definition = definitionsById[filter.key]
    const operator = CUSTOM_PROPERTY_OPERATOR_MAP[filter.operator]
    if (!definition || !operator) {
        return null
    }
    if (
        (operator === AccountsTableCustomPropertyOperator.Contains ||
            operator === AccountsTableCustomPropertyOperator.DoesNotContain) &&
        definition.display_type !== 'text' &&
        definition.display_type !== 'link' &&
        definition.display_type !== 'select'
    ) {
        return null
    }
    if (
        (operator === AccountsTableCustomPropertyOperator.GreaterThan ||
            operator === AccountsTableCustomPropertyOperator.GreaterThanOrEqual ||
            operator === AccountsTableCustomPropertyOperator.LessThan ||
            operator === AccountsTableCustomPropertyOperator.LessThanOrEqual) &&
        !isNumericDisplayType(definition.display_type)
    ) {
        return null
    }
    if (
        (operator === AccountsTableCustomPropertyOperator.DateExact ||
            operator === AccountsTableCustomPropertyOperator.DateBefore ||
            operator === AccountsTableCustomPropertyOperator.DateAfter) &&
        definition.display_type !== 'date' &&
        definition.display_type !== 'datetime'
    ) {
        return null
    }
    const rawValues = Array.isArray(filter.value) ? filter.value : filter.value == null ? [] : [filter.value]
    const values = rawValues.filter(
        (value): value is string | number | boolean =>
            typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean'
    )
    const doesNotNeedValues =
        operator === AccountsTableCustomPropertyOperator.IsSet ||
        operator === AccountsTableCustomPropertyOperator.IsNotSet
    if (!doesNotNeedValues && values.length === 0) {
        return null
    }
    return {
        kind: 'custom_property',
        definitionId: filter.key,
        operator,
        values,
    }
}

export function supportedAccountFilters(
    filters: AccountFilter[],
    definitionsById: Record<string, CustomPropertyDefinitionApi>
): AccountFilter[] {
    return filters.filter((filter) =>
        isAccountPropertyFilter(filter)
            ? accountFieldFilter(filter) !== null
            : customPropertyFilter(filter, definitionsById) !== null
    )
}

function queryFilters(input: BuildAccountsTableQueryPlanInput): AccountsTableFilter[] {
    if (input.accountIdFilter) {
        return [{ kind: 'account_id', accountId: input.accountIdFilter } satisfies AccountsTableAccountIdFilter]
    }

    const filters: AccountsTableFilter[] = []
    const search = input.searchQuery.trim()
    if (search) {
        filters.push({ kind: 'search', query: search })
    }
    if (input.tagsFilter.length > 0) {
        filters.push({ kind: 'tags', tagNames: input.tagsFilter } satisfies AccountsTableTagsFilter)
    }
    if (input.allRolesUnassigned) {
        filters.push({ kind: 'unassigned' } satisfies AccountsTableUnassignedFilter)
    }
    if (input.assignedToFilter.length > 0) {
        filters.push({ kind: 'assigned_to', userIds: input.assignedToFilter } satisfies AccountsTableAssignedToFilter)
    }
    for (const filter of input.accountFilters) {
        const translatedFilter = isAccountPropertyFilter(filter)
            ? accountFieldFilter(filter)
            : customPropertyFilter(filter, input.customPropertyDefinitionsById)
        if (translatedFilter) {
            filters.push(translatedFilter)
        }
    }
    if (input.tileFilter?.filter) {
        const filter = input.tileFilter.filter
        const definition = input.customPropertyDefinitionsById[filter.definitionId]
        if (isUUIDLike(filter.definitionId) && definition && isNumericDisplayType(definition.display_type)) {
            if (filter.operator === AccountsTableCustomPropertyOperator.IsNot) {
                filters.push({
                    kind: 'custom_property',
                    definitionId: filter.definitionId,
                    operator: AccountsTableCustomPropertyOperator.IsSet,
                    values: [],
                })
            }
            filters.push(filter)
        }
    }
    return filters
}

function sortableColumn(column: AccountsTableColumn): AccountsTableSortableColumn {
    if (column.kind === 'custom_property_history') {
        return { kind: 'custom_property', definitionId: column.definitionId }
    }
    return column
}

export function buildAccountsTableQueryPlan(input: BuildAccountsTableQueryPlanInput): AccountsTableQueryPlan {
    const columns: AccountsTablePlannedColumn[] = []
    const columnCount = Math.min(input.querySelectColumns.length, input.visibleColumnNames.length)
    for (let index = 0; index < columnCount; index++) {
        const column = columnFromExpression(input.querySelectColumns[index], input.columnDisplay)
        if (column) {
            columns.push({ visibleName: input.visibleColumnNames[index], column })
        }
    }

    let sort: AccountsTableSort | undefined
    if (input.sortOrder && !input.canSortClientSide) {
        const plannedColumn = columns.find((column) => column.visibleName === input.sortOrder?.column)
        if (plannedColumn) {
            sort = {
                column: sortableColumn(plannedColumn.column),
                direction:
                    input.sortOrder.direction === 'asc'
                        ? AccountsTableSortDirection.Ascending
                        : AccountsTableSortDirection.Descending,
            }
        }
    }

    const filters = queryFilters(input)

    return {
        query: {
            kind: NodeKind.AccountsTableQuery,
            columns: columns.map(({ column }) => column),
            filters,
            includeChurned: input.accountIdFilter !== null,
            includeIgnored: input.accountIdFilter !== null,
            sort,
            tags: { ...CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS, name: 'customer_analytics_accounts_list' },
        },
        columns,
    }
}

function accountFieldValue(row: AccountsTableRow, field: AccountsTableAccountField): unknown {
    if (field === AccountsTableAccountField.Name) {
        return { id: row.id, name: row.name, external_id: row.externalId ?? null }
    }
    if (field === AccountsTableAccountField.ExternalId) {
        return row.externalId ?? null
    }
    return row.accountFields[field] ?? null
}

export function accountsTableCell(row: AccountsTableRow, visibleName: string, plan: AccountsTableQueryPlan): unknown {
    const column = plan.columns.find((candidate) => candidate.visibleName === visibleName)?.column
    if (!column) {
        return undefined
    }
    switch (column.kind) {
        case 'account_field':
            return accountFieldValue(row, column.field)
        case 'tags':
            return row.tags ?? []
        case 'note_count':
            return row.noteCount ?? 0
        case 'relationship':
            return row.relationships[column.definitionId] ?? []
        case 'custom_property':
            return row.customProperties[column.definitionId] ?? null
        case 'custom_property_history':
            return row.customPropertyHistory[column.definitionId] ?? []
    }
}

export function isAccountsTableRow(value: unknown): value is AccountsTableRow {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return false
    }
    const row = value as Partial<AccountsTableRow>
    return (
        typeof row.id === 'string' &&
        typeof row.name === 'string' &&
        !!row.accountFields &&
        !!row.relationships &&
        !!row.customProperties &&
        !!row.customPropertyHistory
    )
}
