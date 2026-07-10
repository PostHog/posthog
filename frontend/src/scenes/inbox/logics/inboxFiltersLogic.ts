import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { INBOX_SCOPE_FOR_YOU, InboxScope, SignalReportPriority } from '../types'
import type { inboxFiltersLogicType } from './inboxFiltersLogicType'

/** A teammate who can be scoped to / suggested as a reviewer. Matches the `available_reviewers` API row. */
export interface InboxReviewerOption {
    user_uuid: string
    name: string
    email: string
}

export type InboxSortField = 'priority' | 'created_at' | 'updated_at'
export type InboxSortDirection = 'asc' | 'desc'

/**
 * Build the `ordering` query param. The list is a flat list (no status section
 * headers), so the toolbar-selected field must lead — otherwise an explicit sort
 * like "Newest first" only reorders reports *within* each status bucket and the
 * genuinely newest reports never reach the top:
 * 1. Toolbar-selected field (priority, updated_at, created_at) with direction
 * 2. Status rank (semantic server-side rank) as a secondary key, so reports tied
 *    on the selected field surface in pipeline-status order
 * 3. `-updated_at` as a final recency tiebreak (skipped when the selected field
 *    is already `updated_at`).
 *
 * Reviewer scope is NOT an ordering tiebreak. A `-is_suggested_reviewer` sort
 * floats the current user's own reports to the top of the single loaded page,
 * which starves the "Entire project" scope of genuinely project-wide reports
 * once the list exceeds one page. Scope is applied separately (client-side here),
 * matching desktop fix #2699.
 */
export function buildSignalReportListOrdering(field: InboxSortField, direction: InboxSortDirection): string {
    const fieldKey = direction === 'desc' ? `-${field}` : field
    return field === 'updated_at' ? `${fieldKey},status` : `${fieldKey},status,-updated_at`
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
        // Auto-select a default scope (e.g. Entire project when the user has no assigned reports)
        // without marking it as an explicit user choice, so a later real choice still wins and persists.
        applyDefaultScope: (scope: InboxScope) => ({ scope }),
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
                applyDefaultScope: (_, { scope }) => scope,
            },
        ],
        // Whether the user has explicitly picked a scope. Once true, the empty-inbox auto-default
        // no longer fires, so a deliberate choice of "For you" is respected even with zero reports.
        hasUserChosenScope: [
            false,
            { persist: true },
            {
                setScope: () => true,
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

    selectors({
        // Whether any list-narrowing filter is active. Scope and sort are excluded: they don't hide
        // reports the way search/source/priority do, and `clearFilters` leaves them untouched.
        hasActiveFilters: [
            (s) => [s.searchQuery, s.sourceProductFilter, s.priorityFilter],
            (searchQuery, sourceProductFilter, priorityFilter): boolean =>
                searchQuery.trim().length > 0 || sourceProductFilter.length > 0 || priorityFilter.length > 0,
        ],
    }),

    afterMount(({ actions }) => {
        actions.loadAvailableReviewers()
    }),
])
