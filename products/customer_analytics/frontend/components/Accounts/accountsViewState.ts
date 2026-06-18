import { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { ACCOUNTS_HOGQL_DEFAULT_SELECT } from './accountsColumnConfigLogic'
import type { AccountSortOrder, RoleFilterValue } from './accountsLogic'
import type { AccountsOverviewTile, TileFilter } from './accountsOverviewTilesLogic'
import { DEFAULT_TILES } from './constants'

export interface AccountsViewFilters {
    search: string
    tags: string[]
    unassigned: boolean
    assignedTo: RoleFilterValue
    tileFilter: TileFilter | null
}

export interface AccountsViewProperties {
    tiles?: AccountsOverviewTile[]
}

export interface AccountsViewState {
    columns: string[]
    sortOrder: AccountSortOrder
    filters: AccountsViewFilters
    tiles: AccountsOverviewTile[]
}

type AccountsViewPayload = Pick<ColumnConfigurationApi, 'columns' | 'order_by'> & {
    filters: Partial<AccountsViewFilters>
    properties: AccountsViewProperties
}

// A persisted filter may be a single id (e.g. `assignedTo: 7`) from before the filter
// became multi-select. Coerce any scalar (or malformed value) into a `number[]`
// so restoring a legacy link/view can't poison the array.
export function normalizeRoleFilter(value: unknown): RoleFilterValue {
    if (Array.isArray(value)) {
        return value.filter((entry): entry is number => typeof entry === 'number')
    }
    return typeof value === 'number' ? [value] : []
}

// Sort persists as a single `["<column> <ASC|DESC>"]` entry using the LOGICAL
// column name (e.g. `csm`); `deriveAccountsOrderByExpr` re-derives the tuple
// expression at query-build time.
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
    if (state.filters.unassigned) {
        filters.unassigned = true
    }
    if (state.filters.assignedTo.length > 0) {
        filters.assignedTo = state.filters.assignedTo
    }
    if (state.filters.tileFilter) {
        filters.tileFilter = state.filters.tileFilter
    }
    return {
        columns: state.columns,
        order_by: sortOrderToOrderBy(state.sortOrder),
        filters,
        properties: { tiles: state.tiles },
    }
}

export function deserializeAccountsView(view: Partial<ColumnConfigurationApi>): AccountsViewState {
    // The backend normalizes empty filters to `[]`; treat any non-object as empty.
    const rawFilters = (
        view.filters && !Array.isArray(view.filters) ? view.filters : {}
    ) as Partial<AccountsViewFilters>
    const rawProperties = (
        view.properties && typeof view.properties === 'object' ? view.properties : {}
    ) as AccountsViewProperties

    return {
        columns: view.columns && view.columns.length > 0 ? view.columns : [...ACCOUNTS_HOGQL_DEFAULT_SELECT],
        sortOrder: orderByToSortOrder(view.order_by),
        filters: {
            search: rawFilters.search ?? '',
            tags: rawFilters.tags ?? [],
            unassigned: rawFilters.unassigned ?? false,
            assignedTo: normalizeRoleFilter(rawFilters.assignedTo),
            tileFilter: rawFilters.tileFilter ?? null,
        },
        tiles: rawProperties.tiles && rawProperties.tiles.length > 0 ? rawProperties.tiles : [...DEFAULT_TILES],
    }
}
