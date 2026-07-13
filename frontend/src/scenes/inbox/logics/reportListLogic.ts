import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { lemonToast } from '@posthog/lemon-ui'

import api, { CountedPaginatedResponse } from 'lib/api'
import { userLogic } from 'scenes/userLogic'

import { captureInboxReportAction } from '../inboxAnalytics'
import {
    ACTIONABLE_ACTIONABILITY_VALUES,
    INBOX_SCOPE_ENTIRE_PROJECT,
    INBOX_SCOPE_FOR_YOU,
    InboxFlatListTabKey,
    InboxScope,
    SignalReport,
} from '../types'
import { DismissalReasonValue } from '../utils/dismissalReasons'
import { inboxBulkActionsLogic } from './inboxBulkActionsLogic'
import { buildSignalReportListOrdering, inboxFiltersLogic } from './inboxFiltersLogic'
import type { reportListLogicType } from './reportListLogicType'

const PAGE_SIZE = 50

/** Fixed, tab-defining server filter (e.g. `{ has_implementation_pr: 'true' }`). */
export type ReportListParams = Record<string, string>

export interface ReportListLogicProps {
    tabKey: InboxFlatListTabKey
    /** The tab's fixed server filter. User-driven chrome (search/sort/source/priority/scope) is layered on top. */
    listParams: ReportListParams
}

/**
 * The fixed server filter per flat tab – the single source of truth shared by the tab
 * bodies, the count chips, and the scene. Mirrors the backend filters confirmed in the plan.
 */
export const INBOX_FLAT_TAB_LIST_PARAMS: Record<InboxFlatListTabKey, ReportListParams> = {
    pulls: { has_implementation_pr: 'true', status: 'ready' },
    reports: {
        has_implementation_pr: 'false',
        status: 'ready,pending_input',
        actionability: ACTIONABLE_ACTIONABILITY_VALUES.join(','),
    },
    'not-actionable': { actionability: 'not_actionable' },
    // Archive = terminal reports: ones the user dismissed (suppressed, restorable) and ones
    // resolved by a merged implementation PR (terminal, not restorable).
    archived: { status: 'suppressed,resolved' },
}

function teammateUuidFromScope(scope: string): string | undefined {
    return scope.startsWith('teammate:') ? scope.slice('teammate:'.length).trim() || undefined : undefined
}

/**
 * Whether to auto-switch the reviewer scope to Entire project on first load. True only for the
 * Pull requests tab when the user is still on the (default) For-you scope, hasn't chosen a scope
 * themselves, has resolved to a real user, and has zero PRs suggested to them — so a user with
 * nothing assigned doesn't land on an empty view. Pure so the branching is unit-testable without
 * mounting the logic.
 */
export function shouldDefaultToEntireProject(input: {
    tabKey: InboxFlatListTabKey
    scope: InboxScope
    hasUserChosenScope: boolean
    hasResolvedUser: boolean
    count: number | null
}): boolean {
    return (
        input.tabKey === 'pulls' &&
        input.scope === INBOX_SCOPE_FOR_YOU &&
        !input.hasUserChosenScope &&
        input.hasResolvedUser &&
        input.count === 0
    )
}

/**
 * Keyed per-tab report list. Mounted once per flat tab (pulls / reports / not-actionable),
 * each with its own fixed `listParams`, so every tab is its own filtered request with its
 * own accurate `count` and its own pagination. The shared user chrome (search, sort, source,
 * priority, reviewer scope) is connected from `inboxFiltersLogic` and applied on top.
 *
 * `count` loads on mount (cheap `limit=1`) so the tab badge is correct before the contents
 * are fetched. The list itself loads lazily (`ensureLoaded`) only when the tab is rendered.
 */
export const reportListLogic = kea<reportListLogicType>([
    path((tabKey) => ['scenes', 'inbox', 'logics', 'reportListLogic', tabKey]),
    props({} as ReportListLogicProps),
    key((props) => props.tabKey),

    connect(() => ({
        values: [
            inboxFiltersLogic,
            [
                'scope',
                'hasUserChosenScope',
                'searchQuery',
                'sortField',
                'sortDirection',
                'sourceProductFilter',
                'priorityFilter',
            ],
            userLogic,
            ['user'],
        ],
        actions: [
            inboxFiltersLogic,
            [
                'setSearchQuery',
                'setSort',
                'toggleSourceProduct',
                'togglePriority',
                'setScope',
                'applyDefaultScope',
                'clearFilters',
            ],
        ],
    })),

    actions({
        ensureLoaded: true,
        loadMore: true,
        archiveReport: (reportId: string, reason: DismissalReasonValue, note: string) => ({ reportId, reason, note }),
        restoreReport: (reportId: string) => ({ reportId }),
        removeReport: (reportId: string) => ({ reportId }),
        refresh: true,
    }),

    loaders(({ values }) => ({
        // Cheap count-only request (limit=1) – populates the tab badge before contents load.
        count: [
            null as number | null,
            {
                loadCount: async () => {
                    const response = await api.signalReports.list({ ...values.listApiParams, limit: 1 })
                    return response.count
                },
            },
        ],
        reportsResponse: [
            null as CountedPaginatedResponse<SignalReport> | null,
            {
                loadReports: async () => {
                    return await api.signalReports.list({ ...values.listApiParams, offset: 0, limit: PAGE_SIZE })
                },
                loadMoreReports: async () => {
                    const current = values.reportsResponse?.results ?? []
                    const response = await api.signalReports.list({
                        ...values.listApiParams,
                        offset: current.length,
                        limit: PAGE_SIZE,
                    })
                    return { ...response, results: [...current, ...response.results] }
                },
            },
        ],
    })),

    reducers({
        reportsResponse: {
            // Optimistic removal on archive – keeps the list snappy; count refreshes in the background.
            removeReport: (state, { reportId }) =>
                state
                    ? {
                          ...state,
                          results: state.results.filter((r) => r.id !== reportId),
                          count: Math.max(0, state.count - 1),
                      }
                    : state,
        },
        count: {
            removeReport: (state) => (state != null ? Math.max(0, state - 1) : state),
        },
    }),

    selectors({
        // The tab's fixed filter merged with the user-driven chrome + reviewer scope (server-side).
        listApiParams: [
            (s) => [
                s.searchQuery,
                s.sortField,
                s.sortDirection,
                s.sourceProductFilter,
                s.priorityFilter,
                s.scope,
                s.user,
                (_, p) => p.listParams,
            ],
            (searchQuery, sortField, sortDirection, sourceProductFilter, priorityFilter, scope, user, listParams) => {
                const suggestedReviewer =
                    scope === INBOX_SCOPE_FOR_YOU ? (user?.uuid ?? undefined) : teammateUuidFromScope(scope)
                return {
                    ...listParams,
                    search: searchQuery.trim() || undefined,
                    ordering: buildSignalReportListOrdering(sortField, sortDirection),
                    source_product: sourceProductFilter.length > 0 ? sourceProductFilter.join(',') : undefined,
                    priority: priorityFilter.length > 0 ? priorityFilter.join(',') : undefined,
                    suggested_reviewers: suggestedReviewer,
                }
            },
        ],
        reports: [
            (s) => [s.reportsResponse],
            (reportsResponse: CountedPaginatedResponse<SignalReport> | null): SignalReport[] =>
                reportsResponse?.results ?? [],
        ],
        hasMore: [
            (s) => [s.reportsResponse],
            (reportsResponse: CountedPaginatedResponse<SignalReport> | null): boolean =>
                reportsResponse?.next !== null && reportsResponse?.next !== undefined,
        ],
        isLoaded: [(s) => [s.reportsResponse], (reportsResponse): boolean => reportsResponse !== null],
    }),

    listeners(({ actions, values, props }) => ({
        // First For-you count for the Pull requests tab: if the user has no PRs suggested to them,
        // default to Entire project so they don't land on an empty view. Only when they haven't
        // picked a scope themselves, and only once the user's uuid has resolved (so the count is
        // genuinely theirs, not an unfiltered project-wide count).
        loadCountSuccess: () => {
            if (
                shouldDefaultToEntireProject({
                    tabKey: props.tabKey,
                    scope: values.scope,
                    hasUserChosenScope: values.hasUserChosenScope,
                    hasResolvedUser: !!values.user?.uuid,
                    count: values.count,
                })
            ) {
                actions.applyDefaultScope(INBOX_SCOPE_ENTIRE_PROJECT)
            }
        },
        ensureLoaded: () => {
            if (values.reportsResponse === null && !values.reportsResponseLoading) {
                actions.loadReports()
            }
        },
        loadMore: () => {
            if (values.hasMore && !values.reportsResponseLoading) {
                actions.loadMoreReports()
            }
        },
        refresh: () => {
            actions.loadCount()
            if (values.isLoaded) {
                actions.loadReports()
            }
        },
        // User-driven filter/scope changes re-fetch the count always, and the contents if this tab is loaded.
        setSearchQuery: async (_, breakpoint) => {
            await breakpoint(300)
            actions.refresh()
        },
        setSort: () => actions.refresh(),
        toggleSourceProduct: () => actions.refresh(),
        togglePriority: () => actions.refresh(),
        setScope: () => actions.refresh(),
        applyDefaultScope: () => actions.refresh(),
        clearFilters: () => actions.refresh(),
        // For-you scope needs the current user's uuid; reload once it resolves.
        [userLogic.actionTypes.loadUserSuccess]: () => {
            if (values.scope === INBOX_SCOPE_FOR_YOU) {
                actions.refresh()
            }
        },
        archiveReport: async ({ reportId, reason, note }) => {
            actions.removeReport(reportId)
            try {
                await api.signalReports.setState(reportId, {
                    state: 'suppressed',
                    dismissal_reason: reason,
                    ...(note ? { dismissal_note: note } : {}),
                })
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to archive report')
                actions.refresh()
            }
        },
        // Restore a suppressed report back to the inbox (transition to `potential`). Optimistically
        // drops it from the Archived list; the report re-enters the pipeline and resurfaces elsewhere.
        restoreReport: async ({ reportId }) => {
            const report = values.reports.find((r) => r.id === reportId)
            actions.removeReport(reportId)
            try {
                await api.signalReports.setState(reportId, { state: 'potential' })
                // Fire only after the restore persists, matching ReportDetailActions' fallback path.
                captureInboxReportAction({ report, actionType: 'restore', surface: 'list_row' })
                lemonToast.success('Report restored to inbox')
                // Restore maps through restore_target_status server-side, so a report suppressed while
                // resolved returns to `resolved` and still belongs in this tab. Reconcile against the
                // server rather than trusting the optimistic removal, which over-drops those rows.
                actions.refresh()
            } catch (error: any) {
                lemonToast.error(error?.detail || error?.message || 'Failed to restore report')
                actions.refresh()
            }
        },
        // Bulk archive happens in the singleton; refresh this tab once it lands.
        [inboxBulkActionsLogic.actionTypes.bulkDismissSuccess]: () => actions.refresh(),
        // A single report archived elsewhere (e.g. the detail pane) – reconcile this tab against
        // the server so the report leaves Reports/Pull requests and joins Archived, counts included.
        [inboxBulkActionsLogic.actionTypes.reportArchived]: () => actions.refresh(),
    })),

    events(({ actions }) => ({
        afterMount: () => {
            actions.loadCount()
        },
    })),
])
