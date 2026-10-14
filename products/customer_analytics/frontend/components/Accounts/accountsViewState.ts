import {
    type AssignmentStatus,
    isAssignmentStatus,
} from 'lib/components/AccountAssignmentFilter/accountAssignmentFilterTypes'

import { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import {
    ACCOUNTS_DEFAULT_COLUMNS,
    AccountColumnDisplayState,
    normalizeAccountColumns,
} from './accountsColumnConfigLogic'
import type { AccountSortOrder, RoleFilterValue } from './accountsLogic'
import type { AccountsOverviewTile, TileFilter } from './accountsOverviewTilesLogic'
import type { AccountFilter } from './accountsPropertyFilters'
import { DEFAULT_TILES } from './constants'

export interface AccountsViewFilters {
    search: string
    assignmentStatus: AssignmentStatus
    assignedTo: RoleFilterValue
    tags: string[]
    tileFilter: TileFilter | null
    customProperties: AccountFilter[]
    filterGroups: AccountFilter[][]
}

interface AccountsViewFiltersRaw extends Partial<AccountsViewFilters> {
    /** @deprecated Legacy field, superseded by `assignmentStatus`. Read for back-compat. */
    unassigned?: boolean
}

// Legacy views and links defaulted to assigned-only. Do not silently broaden them.
function assignmentStatusFromRaw(raw: AccountsViewFiltersRaw): AssignmentStatus {
    if (isAssignmentStatus(raw.assignmentStatus)) {
        return raw.assignmentStatus
    }
    return raw.unassigned ? 'unassigned' : 'assigned'
}

export interface AccountsViewProperties {
    tiles?: AccountsOverviewTile[]
    column_display?: AccountColumnDisplayState
}

export interface AccountsViewState {
    columns: string[]
    sortOrder: AccountSortOrder
    filters: AccountsViewFilters
    tiles: AccountsOverviewTile[]
    columnDisplay: AccountColumnDisplayState
}

export function accountsViewIdStorageKey(teamId: number, userId: string): string {
    return `customerAnalytics.accounts.accountsViewsLogic.${teamId}.${userId}.currentViewId`
}

export interface AccountsViewSelection {
    id: string
    name: string | null
}

export function readAccountsViewSelection(teamId: number, userId?: string): AccountsViewSelection | null {
    try {
        const key = userId
            ? accountsViewIdStorageKey(teamId, userId)
            : `customerAnalytics.accounts.accountsViewsLogic.${teamId}.currentViewId`
        const selection = JSON.parse(window.localStorage.getItem(key) ?? 'null')
        if (typeof selection === 'string' && selection) {
            return { id: selection, name: null }
        }
        if (selection && typeof selection.id === 'string' && selection.id) {
            return { id: selection.id, name: typeof selection.name === 'string' ? selection.name : null }
        }
        return null
    } catch {
        return null
    }
}

export function readAccountsViewId(teamId: number, userId?: string): string | null {
    return readAccountsViewSelection(teamId, userId)?.id ?? null
}

export function writeAccountsViewId(
    teamId: number,
    userId: string,
    id: string | null,
    name: string | null = null
): void {
    try {
        window.localStorage.setItem(accountsViewIdStorageKey(teamId, userId), JSON.stringify(id ? { id, name } : null))
        // Remove the team-only identity only after the scoped preference has been written.
        window.localStorage.removeItem(`customerAnalytics.accounts.accountsViewsLogic.${teamId}.currentViewId`)
    } catch {
        // Storage restrictions must not block view selection.
    }
}

type AccountsViewPayload = Pick<ColumnConfigurationApi, 'columns' | 'order_by'> & {
    filters: Partial<AccountsViewFilters>
    properties: AccountsViewProperties
}

// Older views store a single assignee ID.
export function normalizeRoleFilter(value: unknown): RoleFilterValue {
    if (Array.isArray(value)) {
        return value.filter((entry): entry is number => typeof entry === 'number')
    }
    return typeof value === 'number' ? [value] : []
}

// Persist logical column names so views do not depend on typed query references.
export function sortOrderToOrderBy(sortOrder: AccountSortOrder): string[] {
    if (!sortOrder) {
        return []
    }
    return [`${sortOrder.column} ${sortOrder.direction === 'desc' ? 'DESC' : 'ASC'}`]
}

export function orderByToSortOrder(orderBy: string[] | null | undefined): AccountSortOrder {
    if (!orderBy || orderBy.length === 0) {
        return null
    }
    const match = orderBy[0].match(/^(.*?)\s+(ASC|DESC)$/i)
    if (!match) {
        return { column: orderBy[0].trim(), direction: 'asc' }
    }
    return { column: match[1].trim(), direction: match[2].toUpperCase() === 'DESC' ? 'desc' : 'asc' }
}

export function serializeAccountsView(state: AccountsViewState): AccountsViewPayload {
    const filters: Partial<AccountsViewFilters> = {}
    const search = state.filters.search.trim()
    if (search) {
        filters.search = search
    }
    if (state.filters.tags.length > 0) {
        filters.tags = state.filters.tags
    }
    // Store `all` so new views differ from field-less legacy views.
    filters.assignmentStatus = state.filters.assignmentStatus
    if (state.filters.assignmentStatus === 'assigned' && state.filters.assignedTo.length > 0) {
        filters.assignedTo = state.filters.assignedTo
    }
    if (state.filters.tileFilter) {
        filters.tileFilter = state.filters.tileFilter
    }
    if (state.filters.customProperties.length > 0) {
        filters.customProperties = state.filters.customProperties
    }
    if (state.filters.filterGroups.some((group) => group.length > 0)) {
        filters.filterGroups = state.filters.filterGroups.filter((group) => group.length > 0)
    }
    const properties: AccountsViewProperties = { tiles: state.tiles }
    if (Object.keys(state.columnDisplay).length > 0) {
        properties.column_display = state.columnDisplay
    }
    return {
        columns: state.columns,
        order_by: sortOrderToOrderBy(state.sortOrder),
        filters,
        properties,
    }
}

export function deserializeAccountsView(view: Partial<ColumnConfigurationApi>): AccountsViewState {
    // The backend represents empty filters as an array.
    const rawFilters = (view.filters && !Array.isArray(view.filters) ? view.filters : {}) as AccountsViewFiltersRaw
    const rawProperties = (
        view.properties && typeof view.properties === 'object' ? view.properties : {}
    ) as AccountsViewProperties

    return {
        columns: normalizeAccountColumns(
            view.columns && view.columns.length > 0 ? view.columns : [...ACCOUNTS_DEFAULT_COLUMNS]
        ),
        sortOrder: orderByToSortOrder(view.order_by),
        filters: {
            search: rawFilters.search ?? '',
            assignmentStatus: assignmentStatusFromRaw(rawFilters),
            assignedTo: normalizeRoleFilter(rawFilters.assignedTo),
            tags: rawFilters.tags ?? [],
            tileFilter: rawFilters.tileFilter ?? null,
            customProperties: Array.isArray(rawFilters.customProperties) ? rawFilters.customProperties : [],
            filterGroups: Array.isArray(rawFilters.filterGroups)
                ? rawFilters.filterGroups.filter((group): group is AccountFilter[] => Array.isArray(group))
                : [],
        },
        tiles: rawProperties.tiles && rawProperties.tiles.length > 0 ? rawProperties.tiles : [...DEFAULT_TILES],
        columnDisplay:
            rawProperties.column_display && typeof rawProperties.column_display === 'object'
                ? rawProperties.column_display
                : {},
    }
}
