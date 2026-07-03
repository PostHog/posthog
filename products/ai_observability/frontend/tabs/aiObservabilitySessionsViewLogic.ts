import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
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
        loadSessionsFailure: true,
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

        return {
            loadSessions: async ({ refresh }) => {
                const requestId = ++loadSessionsRequestId
                // A first-page reload supersedes any pagination request already in flight.
                loadMoreSessionsRequestId++
                const source = values.sessionsQuery.source as HogQLQuery
                try {
                    // Default loads use cache (fast, PostHog convention); the Refresh button forces a recompute
                    const response = await api.query(source, { refresh })
                    if (requestId !== loadSessionsRequestId) {
                        return
                    }
                    if (values.sessionsQuery.source !== source) {
                        actions.loadSessionsFailure()
                        return
                    }
                    const sessions = parseSessionsResponse(response)
                    actions.loadSessionsSuccess(sessions, sessions.length === SESSIONS_PAGE_SIZE)
                } catch {
                    if (requestId === loadSessionsRequestId) {
                        actions.loadSessionsFailure()
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
                    const response = await api.query({
                        ...source,
                        query: buildSessionsQuery(values.sessionsSort, offset),
                    })
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
