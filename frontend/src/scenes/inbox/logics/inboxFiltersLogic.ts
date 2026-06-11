import { actions, kea, path, reducers } from 'kea'

import { INBOX_SCOPE_FOR_YOU, InboxScope, SignalReportPriority, SignalReportStatus } from '../types'
import type { inboxFiltersLogicType } from './inboxFiltersLogicType'

/**
 * Status set always sent to the list API: every in-flight pipeline status.
 * Mirrors desktop `INBOX_PIPELINE_STATUS_FILTER`. There is no user-facing status
 * filter (desktop dropped it in filter-store v2); status is a fixed request
 * constant, and tab membership does the rest of the partitioning client-side.
 */
export const INBOX_PIPELINE_STATUS_FILTERS: SignalReportStatus[] = [
    SignalReportStatus.POTENTIAL,
    SignalReportStatus.CANDIDATE,
    SignalReportStatus.IN_PROGRESS,
    SignalReportStatus.READY,
    SignalReportStatus.PENDING_INPUT,
    SignalReportStatus.FAILED,
]

export type InboxSortField = 'priority' | 'created_at' | 'total_weight'
export type InboxSortDirection = 'asc' | 'desc'

/** Build the `ordering` query param. Mirrors desktop `buildSignalReportListOrdering`. */
export function buildSignalReportListOrdering(field: InboxSortField, direction: InboxSortDirection): string {
    const fieldKey = direction === 'desc' ? `-${field}` : field
    return `status,-is_suggested_reviewer,${fieldKey}`
}

/**
 * Persisted inbox filter state. Mirrors desktop's zustand stores:
 * - `inboxReviewerScopeStore` → `scope` (persisted, default "for-you")
 * - `inboxSignalsFilterStore` v2 → `sortField`/`sortDirection` (default priority/asc),
 *   `sourceProductFilter`, `priorityFilter` (all persisted). `searchQuery` is NOT
 *   persisted on desktop, so it isn't here either.
 *
 * The central `inboxSceneLogic` connects these values, maps them to list-API
 * params (`source_product`, `priority`, `ordering`), and reloads on change.
 */
export const inboxFiltersLogic = kea<inboxFiltersLogicType>([
    path(['scenes', 'inbox', 'logics', 'inboxFiltersLogic']),

    actions({
        setScope: (scope: InboxScope) => ({ scope }),
        setSearchQuery: (searchQuery: string) => ({ searchQuery }),
        setSort: (field: InboxSortField, direction: InboxSortDirection) => ({ field, direction }),
        toggleSourceProduct: (source: string) => ({ source }),
        togglePriority: (priority: SignalReportPriority) => ({ priority }),
        clearFilters: true,
    }),

    reducers({
        scope: [
            INBOX_SCOPE_FOR_YOU as InboxScope,
            { persist: true },
            {
                setScope: (_, { scope }) => scope,
            },
        ],
        // Not persisted — matches desktop (searchQuery is excluded from `partialize`).
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
                clearFilters: () => '',
            },
        ],
        sortField: [
            'priority' as InboxSortField,
            { persist: true },
            {
                setSort: (_, { field }) => field,
            },
        ],
        sortDirection: [
            'asc' as InboxSortDirection,
            { persist: true },
            {
                setSort: (_, { direction }) => direction,
            },
        ],
        sourceProductFilter: [
            [] as string[],
            { persist: true },
            {
                toggleSourceProduct: (state, { source }) =>
                    state.includes(source) ? state.filter((s) => s !== source) : [...state, source],
                clearFilters: () => [],
            },
        ],
        priorityFilter: [
            [] as SignalReportPriority[],
            { persist: true },
            {
                togglePriority: (state, { priority }) =>
                    state.includes(priority) ? state.filter((p) => p !== priority) : [...state, priority],
                clearFilters: () => [],
            },
        ],
    }),
])
