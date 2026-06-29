import { actions, connect, kea, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
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

export interface SessionListRow {
    sessionId: string
    distinctId: string
    traces: number
    totalCost: number
    totalLatency: number
    errors: number
    lastSeen: string
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
    }),

    reducers({
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

    loaders(({ values }) => ({
        sessions: [
            [] as SessionListRow[],
            {
                loadSessions: async (payload?: { refresh?: RefreshType }): Promise<SessionListRow[]> => {
                    const source = values.sessionsQuery.source as HogQLQuery
                    // Default loads use cache (fast, PostHog convention); the Refresh button forces a recompute
                    const response = await api.query(source, { refresh: payload?.refresh })
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
                },
            },
        ],
    })),

    listeners(({ actions, values }) => ({
        // Pre-load titles for the whole list (batched + deduped), so each row shows
        // its name and re-selecting a listed session never re-queries its title.
        loadSessionsSuccess: ({ sessions }) => {
            for (const session of sessions) {
                actions.ensureSessionTitleLoaded(session.sessionId, values.dateFilter)
            }
        },
    })),

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
                const query = sessionsQueryTemplate
                    .replace('__ORDER_BY__', sessionsSort.column)
                    .replace('__ORDER_DIRECTION__', sessionsSort.direction)

                return {
                    kind: NodeKind.DataTableNode,
                    source: {
                        kind: NodeKind.HogQLQuery,
                        query,
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
                    showSearch: true,
                    showPropertyFilter: [
                        TaxonomicFilterGroupType.EventProperties,
                        TaxonomicFilterGroupType.PersonProperties,
                        ...groupsTaxonomicTypes,
                        TaxonomicFilterGroupType.Cohorts,
                        TaxonomicFilterGroupType.HogQLExpression,
                    ],
                    showTestAccountFilters: true,
                    showExport: true,
                    showColumnConfigurator: true,
                    allowSorting: true,
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
