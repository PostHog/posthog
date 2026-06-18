import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { INBOX_SCOPE_FOR_YOU, InboxScope, SignalReportPriority, SignalReportStatus } from '../types'
import type { inboxFiltersLogicType } from './inboxFiltersLogicType'

/** A teammate who can be scoped to / suggested as a reviewer. Matches the `available_reviewers` API row. */
export interface InboxReviewerOption {
    user_uuid: string
    name: string
    email: string
}

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

export type InboxSortField = 'priority' | 'created_at' | 'updated_at'
export type InboxSortDirection = 'asc' | 'desc'

/**
 * Build the `ordering` query param. Mirrors desktop `buildSignalReportListOrdering`:
 * 1. Status rank (semantic server-side rank, always applied)
 * 2. Toolbar-selected field (priority, updated_at, created_at)
 * 3. `-updated_at` as a recency tiebreak, so reports tied on status + field
 *    surface most-recently-updated first instead of in arbitrary order.
 *    (Skipped when the selected field is already `updated_at`.)
 *
 * Reviewer scope is NOT an ordering tiebreak. A `-is_suggested_reviewer` sort
 * floats the current user's own reports to the top of the single loaded page,
 * which starves the "Entire project" scope of genuinely project-wide reports
 * once the list exceeds one page. Scope is applied separately (client-side here),
 * matching desktop fix #2699.
 */
export function buildSignalReportListOrdering(field: InboxSortField, direction: InboxSortDirection): string {
    const fieldKey = direction === 'desc' ? `-${field}` : field
    return field === 'updated_at' ? `status,${fieldKey}` : `status,${fieldKey},-updated_at`
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
        // Debounced server-side org-member search for the scope (teammate) picker.
        searchAvailableReviewers: (query: string) => ({ query }),
    }),

    loaders({
        // Shared, project-wide reviewer roster used by the scope picker. Filtered server-side via
        // `query` (backend ranks + caps at 100) so the picker isn't limited to the alphabetical first page.
        availableReviewers: [
            [] as InboxReviewerOption[],
            {
                loadAvailableReviewers: async ({ query }: { query?: string } = {}) => {
                    // The api wrapper already returns the typed `{ user_uuid, name, email }[]` array.
                    return await api.signalReports.availableReviewers(query)
                },
            },
        ],
    }),

    listeners(({ actions }) => ({
        searchAvailableReviewers: async ({ query }, breakpoint) => {
            await breakpoint(300)
            actions.loadAvailableReviewers({ query: query.trim() || undefined })
        },
    })),

    reducers({
        scope: [
            INBOX_SCOPE_FOR_YOU as InboxScope,
            { persist: true },
            {
                setScope: (_, { scope }) => scope,
            },
        ],
        // Not persisted – matches desktop (searchQuery is excluded from `partialize`).
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

    afterMount(({ actions }) => {
        actions.loadAvailableReviewers()
    }),
])
