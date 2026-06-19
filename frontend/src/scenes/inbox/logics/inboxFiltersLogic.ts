import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'

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
 * Inbox filter state, backed by `sessionStorage` (not `localStorage`). Filters
 * survive in-session reloads but reset when the tab — or, in the desktop app, the
 * window — closes. Persisting them across sessions was confusing: an empty inbox
 * left by a forgotten filter looked broken (PostHog papercut).
 *
 * State covered: `scope` (default "for-you"), `sortField`/`sortDirection` (default
 * priority/asc), `sourceProductFilter`, `priorityFilter`. `searchQuery` is never
 * stored. Defaults hydrate from `sessionStorage` at build time; a subscription
 * writes each value back on change (see below).
 *
 * The central `inboxSceneLogic` connects these values, maps them to list-API
 * params (`source_product`, `priority`, `ordering`), and reloads on change.
 */
const SESSION_STORAGE_PREFIX = 'posthog.inboxFilters'

function readSessionFilter<T>(key: string, fallback: T): T {
    try {
        const raw = window.sessionStorage?.getItem(`${SESSION_STORAGE_PREFIX}.${key}`)
        return raw != null ? (JSON.parse(raw) as T) : fallback
    } catch {
        // sessionStorage unavailable (private mode / restricted) or malformed JSON — fall back to default.
        return fallback
    }
}

function writeSessionFilter(key: string, value: unknown): void {
    try {
        window.sessionStorage?.setItem(`${SESSION_STORAGE_PREFIX}.${key}`, JSON.stringify(value))
    } catch {
        // sessionStorage unavailable — filters just won't survive a reload, which is acceptable.
    }
}

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
            readSessionFilter<InboxScope>('scope', INBOX_SCOPE_FOR_YOU),
            {
                setScope: (_, { scope }) => scope,
            },
        ],
        // Never stored — matches desktop (searchQuery is excluded from `partialize`).
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
                clearFilters: () => '',
            },
        ],
        sortField: [
            readSessionFilter<InboxSortField>('sortField', 'priority'),
            {
                setSort: (_, { field }) => field,
            },
        ],
        sortDirection: [
            readSessionFilter<InboxSortDirection>('sortDirection', 'asc'),
            {
                setSort: (_, { direction }) => direction,
            },
        ],
        sourceProductFilter: [
            readSessionFilter<string[]>('sourceProductFilter', []),
            {
                toggleSourceProduct: (state, { source }) =>
                    state.includes(source) ? state.filter((s) => s !== source) : [...state, source],
                clearFilters: () => [],
            },
        ],
        priorityFilter: [
            readSessionFilter<SignalReportPriority[]>('priorityFilter', []),
            {
                togglePriority: (state, { priority }) =>
                    state.includes(priority) ? state.filter((p) => p !== priority) : [...state, priority],
                clearFilters: () => [],
            },
        ],
    }),

    // Mirror each filter into sessionStorage so it survives in-session reloads but resets on tab/window close.
    subscriptions(() => ({
        scope: (scope: InboxScope) => writeSessionFilter('scope', scope),
        sortField: (sortField: InboxSortField) => writeSessionFilter('sortField', sortField),
        sortDirection: (sortDirection: InboxSortDirection) => writeSessionFilter('sortDirection', sortDirection),
        sourceProductFilter: (sourceProductFilter: string[]) =>
            writeSessionFilter('sourceProductFilter', sourceProductFilter),
        priorityFilter: (priorityFilter: SignalReportPriority[]) =>
            writeSessionFilter('priorityFilter', priorityFilter),
    })),

    afterMount(({ actions }) => {
        actions.loadAvailableReviewers()
    }),
])
