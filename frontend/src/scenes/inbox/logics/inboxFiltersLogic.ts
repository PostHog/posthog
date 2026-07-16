import { MakeLogicType, actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, router, urlToAction } from 'kea-router'

import api from 'lib/api'
import { isUUIDLike } from 'lib/utils/guards'
import { urls } from 'scenes/urls'

import { INBOX_PRIORITY_OPTIONS, INBOX_SORT_OPTIONS, INBOX_SOURCE_OPTIONS } from '../filterOptions'
import { INBOX_SCOPE_FOR_YOU, InboxScope, SignalReportPriority } from '../types'

/** A teammate who can be scoped to / suggested as a reviewer. Matches the `available_reviewers` API row. */
export interface InboxReviewerOption {
    user_uuid: string
    name: string
    email: string
}

export type InboxSortField = 'priority' | 'created_at' | 'updated_at'
export type InboxSortDirection = 'asc' | 'desc'

const DEFAULT_SORT_FIELD: InboxSortField = 'priority'
const DEFAULT_SORT_DIRECTION: InboxSortDirection = 'asc'

// Query-param keys that mirror the filter state so a view can be shared via URL.
const FILTER_URL_KEYS = ['scope', 'source', 'priority', 'sort', 'search'] as const

const VALID_SOURCE_VALUES = new Set(INBOX_SOURCE_OPTIONS.map((o) => o.value))
const VALID_PRIORITIES = new Set<string>(INBOX_PRIORITY_OPTIONS)
// Only the field/direction combinations the Sort control actually offers — validating the field and
// direction independently would accept keys like `priority:desc` that have no matching UI option.
const VALID_SORT_KEYS = new Set(INBOX_SORT_OPTIONS.map((o) => `${o.field}:${o.direction}`))

export interface InboxFilterState {
    scope: InboxScope
    sourceProductFilter: string[]
    priorityFilter: SignalReportPriority[]
    sortField: InboxSortField
    sortDirection: InboxSortDirection
    searchQuery: string
}

function parseScopeParam(raw: unknown): InboxScope {
    if (typeof raw === 'string') {
        if (raw === 'entire-project') {
            return raw
        }
        // Validate the teammate id so a malformed shared link falls back to the default scope
        // instead of forwarding junk to the report-list API as a reviewer UUID.
        if (raw.startsWith('teammate:') && isUUIDLike(raw.slice('teammate:'.length))) {
            return raw as InboxScope
        }
    }
    return INBOX_SCOPE_FOR_YOU
}

function parseListParam(raw: unknown, valid: Set<string>): string[] {
    if (typeof raw !== 'string' || raw.length === 0) {
        return []
    }
    return raw.split(',').filter((v) => valid.has(v))
}

/** Decode the filter query params into filter state, ignoring unknown/invalid values and falling back to defaults. */
export function parseFilterSearchParams(searchParams: Record<string, any>): InboxFilterState {
    let sortField = DEFAULT_SORT_FIELD
    let sortDirection = DEFAULT_SORT_DIRECTION
    if (typeof searchParams.sort === 'string' && VALID_SORT_KEYS.has(searchParams.sort)) {
        const [field, direction] = searchParams.sort.split(':')
        sortField = field as InboxSortField
        sortDirection = direction as InboxSortDirection
    }
    return {
        scope: parseScopeParam(searchParams.scope),
        sourceProductFilter: parseListParam(searchParams.source, VALID_SOURCE_VALUES),
        priorityFilter: parseListParam(searchParams.priority, VALID_PRIORITIES) as SignalReportPriority[],
        sortField,
        sortDirection,
        searchQuery: typeof searchParams.search === 'string' ? searchParams.search : '',
    }
}

function sameSet(a: string[], b: string[]): boolean {
    return a.length === b.length && [...a].sort().join(',') === [...b].sort().join(',')
}

/** Build the query params that mirror the current (non-default) filter state. Defaults are omitted so a shared URL stays clean. */
export function filterSearchParams(values: InboxFilterState): Record<string, string> {
    const params: Record<string, string> = {}
    if (values.scope !== INBOX_SCOPE_FOR_YOU) {
        params.scope = values.scope
    }
    if (values.sourceProductFilter.length > 0) {
        params.source = values.sourceProductFilter.join(',')
    }
    if (values.priorityFilter.length > 0) {
        params.priority = values.priorityFilter.join(',')
    }
    if (values.sortField !== DEFAULT_SORT_FIELD || values.sortDirection !== DEFAULT_SORT_DIRECTION) {
        params.sort = `${values.sortField}:${values.sortDirection}`
    }
    if (values.searchQuery.trim().length > 0) {
        params.search = values.searchQuery
    }
    return params
}

/**
 * Build the state-mirroring inbox URL for the current pathname: keep any non-filter query params,
 * drop stale filter keys, then write the current non-default filter state back on. `replace: true`
 * keeps filter toggles out of the browser history.
 */
function currentUrlWithFilters(values: InboxFilterState): [string, Record<string, any>, any, { replace: boolean }] {
    const searchParams = { ...router.values.searchParams }
    for (const key of FILTER_URL_KEYS) {
        delete searchParams[key]
    }
    Object.assign(searchParams, filterSearchParams(values))
    return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
}

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

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxFiltersLogicValues {
    availableReviewers: InboxReviewerOption[]
    availableReviewersLoading: boolean
    hasActiveFilters: boolean
    hasUserChosenScope: boolean
    priorityFilter: SignalReportPriority[]
    scope: InboxScope
    searchQuery: string
    sortDirection: InboxSortDirection
    sortField: InboxSortField
    sourceProductFilter: string[]
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxFiltersLogicActions {
    applyDefaultScope: (scope: InboxScope) => {
        scope: InboxScope
    }
    clearFilters: () => {
        value: true
    }
    loadAvailableReviewers: ({ query }?: { query?: string }) => {
        query?: string
    }
    loadAvailableReviewersFailure: (
        error: string,
        errorObject?: any
    ) => {
        error: string
        errorObject?: any
    }
    loadAvailableReviewersSuccess: (
        availableReviewers: {
            email: string
            name: string
            user_uuid: string
        }[],
        payload?: {
            query?: string
        }
    ) => {
        availableReviewers: {
            email: string
            name: string
            user_uuid: string
        }[]
        payload?: {
            query?: string
        }
    }
    searchAvailableReviewers: (query: string) => {
        query: string
    }
    setFilters: (filters: InboxFilterState) => {
        filters: InboxFilterState
    }
    setScope: (scope: InboxScope) => {
        scope: InboxScope
    }
    setSearchQuery: (searchQuery: string) => {
        searchQuery: string
    }
    setSort: (
        field: InboxSortField,
        direction: InboxSortDirection
    ) => {
        direction: InboxSortDirection
        field: InboxSortField
    }
    togglePriority: (priority: SignalReportPriority) => {
        priority: SignalReportPriority
    }
    toggleSourceProduct: (source: string) => {
        source: string
    }
}

// Generated by kea-typegen. Update if you're an agent, ignore if you're human.
export interface inboxFiltersLogicMeta {
    __keaTypeGenInternalSelectorTypes: {
        hasActiveFilters: (
            searchQuery: string,
            sourceProductFilter: string[],
            priorityFilter: SignalReportPriority[]
        ) => boolean
    }
}

export type inboxFiltersLogicType = MakeLogicType<
    inboxFiltersLogicValues,
    inboxFiltersLogicActions,
    Record<string, any>,
    inboxFiltersLogicMeta
>

/**
 * Persisted inbox filter state. Mirrors desktop's zustand stores:
 * - `inboxReviewerScopeStore` → `scope` (persisted, default "for-you")
 * - `inboxSignalsFilterStore` v2 → `sortField`/`sortDirection` (default priority/asc),
 *   `sourceProductFilter`, `priorityFilter` (all persisted). `searchQuery` is NOT
 *   persisted on desktop, so it isn't here either.
 *
 * Filter state (scope, source, priority, sort) is also mirrored to the URL query
 * string so a specific view can be shared via a link. The URL is authoritative on
 * load whenever any filter param is present; a bare `/inbox` falls back to the
 * persisted state (and is then reflected back into the URL so it stays shareable).
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
        // Atomically apply a full filter set. Used when hydrating from a shared URL so the whole view
        // is restored in one action — one list refresh, no fan-out race between partial states.
        setFilters: (filters: InboxFilterState) => ({ filters }),
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
                setFilters: (_, { filters }) => filters.scope,
            },
        ],
        // Whether the user has explicitly picked a scope. Once true, the empty-inbox auto-default
        // no longer fires, so a deliberate choice of "For you" is respected even with zero reports.
        // A shared link is an explicit choice too, so hydrating from the URL sets it.
        hasUserChosenScope: [
            false,
            { persist: true },
            {
                setScope: () => true,
                setFilters: () => true,
            },
        ],
        // Not persisted – matches desktop (searchQuery is excluded from `partialize`). It is mirrored to
        // the URL though, so a shared link reproduces the search too and hydration can reset it.
        searchQuery: [
            '',
            {
                setSearchQuery: (_, { searchQuery }) => searchQuery,
                setFilters: (_, { filters }) => filters.searchQuery,
                clearFilters: () => '',
            },
        ],
        sortField: [
            DEFAULT_SORT_FIELD as InboxSortField,
            { persist: true },
            {
                setSort: (_, { field }) => field,
                setFilters: (_, { filters }) => filters.sortField,
            },
        ],
        sortDirection: [
            DEFAULT_SORT_DIRECTION as InboxSortDirection,
            { persist: true },
            {
                setSort: (_, { direction }) => direction,
                setFilters: (_, { filters }) => filters.sortDirection,
            },
        ],
        sourceProductFilter: [
            [] as string[],
            { persist: true },
            {
                toggleSourceProduct: (state, { source }) =>
                    state.includes(source) ? state.filter((s) => s !== source) : [...state, source],
                setFilters: (_, { filters }) => filters.sourceProductFilter,
                clearFilters: () => [],
            },
        ],
        priorityFilter: [
            [] as SignalReportPriority[],
            { persist: true },
            {
                togglePriority: (state, { priority }) =>
                    state.includes(priority) ? state.filter((p) => p !== priority) : [...state, priority],
                setFilters: (_, { filters }) => filters.priorityFilter,
                clearFilters: () => [],
            },
        ],
    }),

    selectors({
        // Whether any list-narrowing filter is active. Scope and sort are excluded: they don't hide
        // reports the way search/source/priority do, and `clearFilters` leaves them untouched.
        hasActiveFilters: [
            (s) => [s.searchQuery, s.sourceProductFilter, s.priorityFilter],
            (searchQuery: string, sourceProductFilter: string[], priorityFilter: SignalReportPriority[]): boolean =>
                searchQuery.trim().length > 0 || sourceProductFilter.length > 0 || priorityFilter.length > 0,
        ],
    }),

    actionToUrl(({ values }) => {
        // Every filter mutation rewrites the current URL from the full (non-default) filter state.
        const toUrl = (): [string, Record<string, any>, any, { replace: boolean }] => currentUrlWithFilters(values)
        // `setFilters` is intentionally absent: it only fires while hydrating from the URL, which is
        // already the source of truth in that path, so re-deriving the URL from it would be redundant.
        return {
            setScope: toUrl,
            applyDefaultScope: toUrl,
            setSort: toUrl,
            toggleSourceProduct: toUrl,
            togglePriority: toUrl,
            setSearchQuery: toUrl,
            clearFilters: toUrl,
        }
    }),

    urlToAction(({ actions, values }) => {
        const applyFromUrl = (_: unknown, searchParams: Record<string, any>): void => {
            const hasFilterParams = FILTER_URL_KEYS.some((key) => key in searchParams)
            if (!hasFilterParams) {
                // Bare inbox URL: keep the persisted state, but reflect any non-default filters back
                // into the URL so the current view is immediately shareable.
                const desired = filterSearchParams(values)
                if (Object.keys(desired).length > 0) {
                    router.actions.replace(
                        router.values.location.pathname,
                        { ...router.values.searchParams, ...desired },
                        router.values.hashParams
                    )
                }
                return
            }

            // A shared link is authoritative: apply the params it carries and reset the rest to defaults.
            // Only dispatch when something actually changed — urlToAction also fires on plain navigation
            // (opening a report, switching tabs), and we don't want a redundant list refresh each time.
            const parsed = parseFilterSearchParams(searchParams)
            const changed =
                values.scope !== parsed.scope ||
                !sameSet(values.sourceProductFilter, parsed.sourceProductFilter) ||
                !sameSet(values.priorityFilter, parsed.priorityFilter) ||
                values.sortField !== parsed.sortField ||
                values.sortDirection !== parsed.sortDirection ||
                values.searchQuery !== parsed.searchQuery
            if (changed) {
                actions.setFilters(parsed)
            }
        }

        return {
            [urls.inbox()]: applyFromUrl,
            [urls.inbox(':tab')]: applyFromUrl,
            [urls.inboxScratchpad()]: applyFromUrl,
            [urls.inboxFindings()]: applyFromUrl,
            [urls.inboxScout(':skillName')]: applyFromUrl,
            [urls.inboxScout(':skillName', ':findingId')]: applyFromUrl,
            [urls.inboxReport(':tab', ':reportId')]: applyFromUrl,
        }
    }),

    afterMount(({ actions }) => {
        actions.loadAvailableReviewers()
    }),
])
