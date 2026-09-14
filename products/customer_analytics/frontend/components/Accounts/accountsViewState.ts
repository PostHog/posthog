import { z } from 'zod'

import {
    type AssignmentStatus,
    isAssignmentStatus,
} from 'lib/components/AccountAssignmentFilter/accountAssignmentFilterTypes'

import { ColumnConfigurationApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { ACCOUNTS_DEFAULT_COLUMNS, AccountColumnDisplayState } from './accountsColumnConfigLogic'
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
}

// A raw persisted filter object may predate `assignmentStatus` and carry only the legacy
// `unassigned` boolean. Read both so restoring an old view can resolve a status.
interface AccountsViewFiltersRaw extends Partial<AccountsViewFilters> {
    /** @deprecated Legacy field, superseded by `assignmentStatus`. Read for back-compat. */
    unassigned?: boolean
}

// A saved view or shared link created before `assignmentStatus` existed defaulted to
// assigned-only. Resolve legacy filters to that status so they never silently broaden.
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

const ACCOUNTS_VIEW_DRAFT_STORAGE_KEY = 'customerAnalytics.accounts.viewDraft'

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

// Sort persists under the logical column name so saved views do not depend on
// the typed query's relationship or custom-property references.
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
    // Always store the status so a new "all" view is distinct from a legacy view with no
    // field (which restores as assigned-only). Assigned-to only narrows the assigned status.
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

const StoredTile = z.object({
    id: z.string(),
    label: z.string(),
    metric: z.discriminatedUnion('type', [
        z.object({ type: z.literal('count') }),
        z.object({
            type: z.enum(['sum', 'avg', 'min', 'max', 'median']),
            columnExpression: z.string(),
            columnLabel: z.string(),
            scale: z.number().optional(),
        }),
        z.object({
            type: z.literal('count_threshold'),
            columnExpression: z.string(),
            columnLabel: z.string(),
            operator: z.string(),
            value: z.number(),
        }),
    ]),
    caption: z.string().optional(),
    format: z.enum(['unit', 'currency', 'percentage']).optional(),
})

const AccountsViewDraft = z.object({
    columns: z.array(z.string()),
    sortOrder: z.object({ column: z.string(), direction: z.enum(['asc', 'desc']) }).nullable(),
    filters: z.object({
        search: z.string(),
        assignmentStatus: z.enum(['all', 'assigned', 'unassigned']),
        assignedTo: z.array(z.number()),
        tags: z.array(z.string()),
        tileFilter: z
            .object({
                tileId: z.string(),
                filter: z.object({
                    kind: z.literal('custom_property'),
                    definitionId: z.string(),
                    operator: z.string(),
                    values: z.array(z.number()),
                }),
            })
            .nullable(),
        customProperties: z.array(z.object({}).passthrough()),
    }),
    tiles: z.array(StoredTile),
    columnDisplay: z.record(z.string(), z.object({ mode: z.enum(['sparkline', 'trend']), window_days: z.number() })),
})

export function accountsViewDraftStorageKey(teamId: number, userId: string): string {
    // This key scopes drafts to the browser session, project, and person. Changing it would strand existing drafts.
    return `${ACCOUNTS_VIEW_DRAFT_STORAGE_KEY}.${teamId}.${userId}`
}

export function readAccountsViewDraft(teamId: number | null, userId: string | null): AccountsViewState | null {
    if (teamId === null || userId === null || typeof window === 'undefined') {
        return null
    }
    try {
        const raw = window.sessionStorage.getItem(accountsViewDraftStorageKey(teamId, userId))
        const draft = AccountsViewDraft.safeParse(raw ? JSON.parse(raw) : null)
        return draft.success ? (draft.data as AccountsViewState) : null
    } catch {
        return null
    }
}

export function writeAccountsViewDraft(teamId: number | null, userId: string | null, draft: AccountsViewState): void {
    if (teamId === null || userId === null || typeof window === 'undefined') {
        return
    }
    try {
        window.sessionStorage.setItem(accountsViewDraftStorageKey(teamId, userId), JSON.stringify(draft))
    } catch {
        // Browsers can deny sessionStorage, so list navigation must still work without drafts.
    }
}

export function deserializeAccountsView(view: Partial<ColumnConfigurationApi>): AccountsViewState {
    // The backend normalizes empty filters to `[]`; treat any non-object as empty.
    const rawFilters = (view.filters && !Array.isArray(view.filters) ? view.filters : {}) as AccountsViewFiltersRaw
    const rawProperties = (
        view.properties && typeof view.properties === 'object' ? view.properties : {}
    ) as AccountsViewProperties

    return {
        columns: view.columns && view.columns.length > 0 ? view.columns : [...ACCOUNTS_DEFAULT_COLUMNS],
        sortOrder: orderByToSortOrder(view.order_by),
        filters: {
            search: rawFilters.search ?? '',
            assignmentStatus: assignmentStatusFromRaw(rawFilters),
            assignedTo: normalizeRoleFilter(rawFilters.assignedTo),
            tags: rawFilters.tags ?? [],
            tileFilter: rawFilters.tileFilter ?? null,
            customProperties: Array.isArray(rawFilters.customProperties) ? rawFilters.customProperties : [],
        },
        tiles: rawProperties.tiles && rawProperties.tiles.length > 0 ? rawProperties.tiles : [...DEFAULT_TILES],
        columnDisplay:
            rawProperties.column_display && typeof rawProperties.column_display === 'object'
                ? rawProperties.column_display
                : {},
    }
}
