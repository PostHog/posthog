import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { PromiseTimeoutError, withTimeout } from 'lib/utils/async'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { DataTableNode, HogQLQuery, NodeKind, RefreshType } from '~/queries/schema/schema-general'

import sessionsQueryTemplate from '../../backend/queries/sessions.sql?raw'
import type { SortDirection, SortState } from '../aiObservabilitySharedLogic'
import { aiObservabilitySharedLogic } from '../aiObservabilitySharedLogic'
import { llmSessionTitleLazyLoaderLogic } from '../llmSessionTitleLazyLoaderLogic'
import type { aiObservabilitySessionsViewLogicType } from './aiObservabilitySessionsViewLogicType'

export type AIObservabilitySessionsViewLogicProps = Record<string, never>

const SESSIONS_PAGE_SIZE = 50
// The two-level session aggregation can run long on high-volume projects. Cap it so a
// hung query surfaces a retry state instead of an endless skeleton spinner.
const SESSIONS_QUERY_TIMEOUT_MS = 60_000

// When the sessions list comes back empty, we can't tell from that query alone whether
// there is simply no AI traffic in the window or whether traffic exists but isn't tagged
// with `$ai_session_id` (the `sessions.sql` query drops traces with an empty session id).
// This existence probe checks for AI trace events in the same window regardless of session
// id — LIMIT 1 so ClickHouse stops at the first match instead of scanning the whole window.
const EMPTY_REASON_PROBE_QUERY = `
SELECT 1
FROM events
WHERE event IN ('$ai_generation', '$ai_span', '$ai_embedding', '$ai_trace')
    AND isNotNull(properties.$ai_trace_id)
    AND properties.$ai_trace_id != ''
    AND {filters}
LIMIT 1
`
// The loading state stays up while the probe classifies an empty list, so cap it tighter
// than the main query — on probe timeout we fall back to the generic empty copy.
const EMPTY_REASON_PROBE_TIMEOUT_MS = 15_000

// Why the sessions load failed, surfaced to the UI as a retryable error state.
export type SessionsErrorKind = 'error' | 'timeout' | null
// Why the sessions list is empty, so the empty state can point the user at the right fix.
export type SessionsEmptyReason = 'no-data' | 'no-session-ids' | null

export interface SessionListRow {
    sessionId: string
    distinctId: string
    traces: number
    totalCost: number
    totalLatency: number
    errors: number
    lastSeen: string
}

function buildSessionsQuery(sessionsSort: SortState, offset: number): string {
    return sessionsQueryTemplate
        .replace('__ORDER_BY__', sessionsSort.column)
        .replace('__ORDER_DIRECTION__', sessionsSort.direction)
        .replace('__LIMIT__', String(SESSIONS_PAGE_SIZE))
        .replace('__OFFSET__', String(offset))
}

function parseSessionsResponse(response: { columns?: unknown[]; results?: unknown[] }): SessionListRow[] {
    const columns = (response.columns ?? []) as string[]
    const at = (name: string): number => columns.indexOf(name)
    const rows = (response.results ?? []) as unknown[][]
    return rows.map((row) => ({
        sessionId: String(row[at('session_id')] ?? ''),
        distinctId: String(row[at('distinct_id')] ?? ''),
        traces: Number(row[at('traces')] ?? 0),
        totalCost: Number(row[at('total_cost')] ?? 0),
        totalLatency: Number(row[at('total_latency')] ?? 0),
        errors: Number(row[at('errors')] ?? 0),
        lastSeen: String(row[at('last_seen')] ?? ''),
    }))
}

export const aiObservabilitySessionsViewLogic = kea<aiObservabilitySessionsViewLogicType>([
    path(['products', 'ai_observability', 'frontend', 'tabs', 'aiObservabilitySessionsViewLogic']),
    props({} as AIObservabilitySessionsViewLogicProps),
    connect(() => ({
        values: [
            aiObservabilitySharedLogic,
            ['activeTab', 'dateFilter', 'shouldFilterTestAccounts', 'propertyFilters'],
            groupsModel,
            ['groupsTaxonomicTypes'],
            llmSessionTitleLazyLoaderLogic,
            ['getSessionTitle'],
        ],
        actions: [llmSessionTitleLazyLoaderLogic, ['ensureSessionTitleLoaded']],
    })),

    actions({
        setSessionsSort: (column: string, direction: SortDirection) => ({ column, direction }),
        selectSession: (sessionId: string | null) => ({ sessionId }),
        loadSessions: (payload?: { refresh?: RefreshType }) => ({ refresh: payload?.refresh }),
        loadSessionsSuccess: (sessions: SessionListRow[], hasMoreSessions: boolean) => ({ sessions, hasMoreSessions }),
        loadSessionsFailure: (timedOut: boolean = false) => ({ timedOut }),
        setSessionsEmptyReason: (reason: SessionsEmptyReason) => ({ reason }),
        loadMoreSessions: true,
        loadMoreSessionsSuccess: (sessions: SessionListRow[], hasMoreSessions: boolean) => ({
            sessions,
            hasMoreSessions,
        }),
        loadMoreSessionsFailure: true,
    }),

    reducers({
        sessions: [
            [] as SessionListRow[],
            {
                loadSessionsSuccess: (_, { sessions }) => sessions,
                loadMoreSessionsSuccess: (state, { sessions }) => [...state, ...sessions],
            },
        ],
        sessionsLoading: [
            false,
            {
                loadSessions: () => true,
                loadSessionsSuccess: () => false,
                loadSessionsFailure: () => false,
            },
        ],
        moreSessionsLoading: [
            false,
            {
                loadSessions: () => false,
                loadMoreSessions: () => true,
                loadMoreSessionsSuccess: () => false,
                loadMoreSessionsFailure: () => false,
            },
        ],
        hasMoreSessions: [
            false,
            {
                loadSessionsSuccess: (_, { hasMoreSessions }) => hasMoreSessions,
                loadMoreSessionsSuccess: (_, { hasMoreSessions }) => hasMoreSessions,
                loadSessionsFailure: () => false,
            },
        ],
        sessionsError: [
            null as SessionsErrorKind,
            {
                loadSessions: () => null,
                loadSessionsSuccess: () => null,
                loadSessionsFailure: (_, { timedOut }) => (timedOut ? 'timeout' : 'error'),
            },
        ],
        sessionsEmptyReason: [
            null as SessionsEmptyReason,
            {
                loadSessions: () => null,
                loadSessionsSuccess: () => null,
                setSessionsEmptyReason: (_, { reason }) => reason,
            },
        ],
        selectedSessionId: [
            null as string | null,
            {
                selectSession: (_, { sessionId }) => sessionId,
            },
        ],
        sessionsSort: [
            { column: 'last_seen', direction: 'DESC' } as SortState,
            {
                setSessionsSort: (_, { column, direction }): SortState => ({ column, direction }),
            },
        ],
    }),

    listeners(({ actions, values }) => {
        let loadSessionsRequestId = 0
        let loadMoreSessionsRequestId = 0

        const preloadSessionTitles = (sessions: SessionListRow[]): void => {
            for (const session of sessions) {
                actions.ensureSessionTitleLoaded(session.sessionId, values.dateFilter)
            }
        }

        // Best-effort classification for an empty list: is there simply no AI traffic in
        // the window, or does traffic exist that just isn't tagged with `$ai_session_id`?
        // Returns null when the probe fails, times out, or is superseded — callers fall
        // back to the generic empty copy. Deliberately unaffected by `refresh`: a cached
        // answer is fine here and keeps the held loading state short.
        const classifyEmptyReason = async (source: HogQLQuery, requestId: number): Promise<SessionsEmptyReason> => {
            try {
                const response = await withTimeout(
                    (signal) =>
                        api.query({ ...source, query: EMPTY_REASON_PROBE_QUERY }, { requestOptions: { signal } }),
                    EMPTY_REASON_PROBE_TIMEOUT_MS,
                    'AI sessions empty-reason probe timed out'
                )
                if (requestId !== loadSessionsRequestId) {
                    return null
                }
                return (response.results?.length ?? 0) > 0 ? 'no-session-ids' : 'no-data'
            } catch {
                return null
            }
        }

        return {
            loadSessions: async ({ refresh }) => {
                const requestId = ++loadSessionsRequestId
                // A first-page reload supersedes any pagination request already in flight.
                loadMoreSessionsRequestId++
                const source = values.sessionsQuery.source as HogQLQuery
                try {
                    // Default loads use cache (fast, PostHog convention); the Refresh button forces a recompute.
                    // Cap the request so a hung aggregation surfaces a retry state instead of spinning forever.
                    const response = await withTimeout(
                        (signal) => api.query(source, { refresh, requestOptions: { signal } }),
                        SESSIONS_QUERY_TIMEOUT_MS,
                        'AI sessions query timed out'
                    )
                    if (requestId !== loadSessionsRequestId) {
                        return
                    }
                    if (values.sessionsQuery.source !== source) {
                        actions.loadSessionsFailure()
                        return
                    }
                    const sessions = parseSessionsResponse(response)
                    if (sessions.length > 0) {
                        actions.loadSessionsSuccess(sessions, sessions.length === SESSIONS_PAGE_SIZE)
                        return
                    }
                    // Keep the loading state up while we classify the empty reason, so the
                    // empty state renders once with the right copy instead of flashing the
                    // generic guidance and then swapping it out under the user.
                    const reason = await classifyEmptyReason(source, requestId)
                    if (requestId !== loadSessionsRequestId) {
                        return
                    }
                    if (values.sessionsQuery.source !== source) {
                        actions.loadSessionsFailure()
                        return
                    }
                    actions.loadSessionsSuccess(sessions, false)
                    if (reason) {
                        actions.setSessionsEmptyReason(reason)
                    }
                } catch (error) {
                    if (requestId === loadSessionsRequestId) {
                        actions.loadSessionsFailure(error instanceof PromiseTimeoutError)
                    }
                }
            },
            loadMoreSessions: async () => {
                if (!values.hasMoreSessions) {
                    actions.loadMoreSessionsFailure()
                    return
                }
                const requestId = ++loadMoreSessionsRequestId
                const source = values.sessionsQuery.source as HogQLQuery
                const offset = values.sessions.length
                try {
                    const paginatedSource = { ...source, query: buildSessionsQuery(values.sessionsSort, offset) }
                    const response = await withTimeout(
                        (signal) => api.query(paginatedSource, { requestOptions: { signal } }),
                        SESSIONS_QUERY_TIMEOUT_MS,
                        'AI sessions query timed out'
                    )
                    if (requestId !== loadMoreSessionsRequestId) {
                        return
                    }
                    if (values.sessionsQuery.source !== source || values.sessions.length !== offset) {
                        actions.loadMoreSessionsFailure()
                        return
                    }
                    const sessions = parseSessionsResponse(response)
                    actions.loadMoreSessionsSuccess(sessions, sessions.length === SESSIONS_PAGE_SIZE)
                } catch {
                    if (requestId === loadMoreSessionsRequestId) {
                        actions.loadMoreSessionsFailure()
                    }
                }
            },
            // Pre-load titles for the whole list (batched + deduped), so each row shows
            // its name and re-selecting a listed session never re-queries its title.
            loadSessionsSuccess: ({ sessions }) => {
                preloadSessionTitles(sessions)
            },
            loadMoreSessionsSuccess: ({ sessions }) => {
                preloadSessionTitles(sessions)
            },
        }
    }),

    selectors({
        sessionsQuery: [
            (s) => [
                s.dateFilter,
                s.shouldFilterTestAccounts,
                s.propertyFilters,
                s.sessionsSort,
                s.groupsTaxonomicTypes,
            ],
            (
                dateFilter: { dateFrom: string | null; dateTo: string | null },
                shouldFilterTestAccounts: boolean,
                propertyFilters,
                sessionsSort: { column: string; direction: 'ASC' | 'DESC' },
                groupsTaxonomicTypes: TaxonomicFilterGroupType[]
            ): DataTableNode => {
                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.HogQLQuery,
                        query: buildSessionsQuery(sessionsSort, 0),
                        filters: {
                            dateRange: {
                                date_from: dateFilter.dateFrom || null,
                                date_to: dateFilter.dateTo || null,
                            },
                            filterTestAccounts: shouldFilterTestAccounts,
                            properties: propertyFilters,
                        },
                    },
                    columns: [
                        'session_id',
                        'distinct_id',
                        'traces',
                        'spans',
                        'generations',
                        'embeddings',
                        'tools',
                        'errors',
                        'total_cost',
                        'total_latency',
                        'first_seen',
                        'last_seen',
                    ],
                    showDateRange: true,
                    showReload: true,
                    showPropertyFilter: [
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        ...groupsTaxonomicTypes,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.HogQLExpression,
                    ],
                    showTestAccountFilters: true,
                    showColumnConfigurator: true,
                }
            },
        ],
    }),

    subscriptions(({ actions, values }) => ({
        sessionsQuery: (_sessionsQuery, previousSessionsQuery: DataTableNode | undefined) => {
            if (previousSessionsQuery === undefined || values.activeTab !== 'sessions') {
                return
            }
            actions.loadSessions()
        },
    })),

    urlToAction(({ actions, values }) => ({
        '/ai-observability/sessions/:id': ({ id }) => {
            if (id && id !== values.selectedSessionId) {
                actions.selectSession(id)
            }
        },
        '/ai-observability/sessions': () => {
            if (values.selectedSessionId) {
                actions.selectSession(null)
            }
        },
    })),

    actionToUrl(() => ({
        selectSession: ({ sessionId }) => {
            const search = router.values.searchParams
            return sessionId
                ? combineUrl(urls.aiObservabilitySession(sessionId), search).url
                : combineUrl(urls.aiObservabilitySessions(), search).url
        },
    })),
])
