import { actions, connect, kea, path, props, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { insightVizDataNodeKey } from '~/queries/nodes/InsightViz/insightVizKeys'
import { AnyResponseType, DataTableNode, NodeKind, SessionQuery } from '~/queries/schema/schema-general'
import { Breadcrumb, InsightLogicProps } from '~/types'

import type { aiObservabilitySessionLogicType } from './aiObservabilitySessionLogicType'
import { aiObservabilitySharedLogic } from './aiObservabilitySharedLogic'

export interface AIObservabilitySessionDataNodeLogicParams {
    sessionId: string
    query: DataTableNode
    cachedResults?: AnyResponseType | null
}

export function getDataNodeLogicProps({
    sessionId,
    query,
    cachedResults,
}: AIObservabilitySessionDataNodeLogicParams): DataNodeLogicProps {
    const insightProps: InsightLogicProps<DataTableNode> = {
        dashboardItemId: `new-Session.${sessionId}`,
        dataNodeCollectionId: sessionId,
    }
    const vizKey = insightVizDataNodeKey(insightProps)
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query.source,
        key: vizKey,
        dataNodeCollectionId: sessionId,
        cachedResults: cachedResults || undefined,
    }
    return dataNodeLogicProps
}

export type AIObservabilitySessionLogicProps = Record<string, never>

export const aiObservabilitySessionLogic = kea<aiObservabilitySessionLogicType>([
    path(['scenes', 'ai-observability', 'aiObservabilitySessionLogic']),
    props({} as AIObservabilitySessionLogicProps),

    connect(() => ({
        values: [aiObservabilitySharedLogic, ['dateFilter']],
    })),

    actions({
        setSessionId: (sessionId: string) => ({ sessionId }),
        setDateRange: (dateFrom: string | null, dateTo?: string | null) => ({ dateFrom, dateTo }),
    }),

    reducers({
        sessionId: ['' as string, { setSessionId: (_, { sessionId }) => sessionId }],
        dateRange: [
            null as { dateFrom: string | null; dateTo: string | null } | null,
            {
                setDateRange: (_, { dateFrom, dateTo }) => ({
                    dateFrom: dateFrom ?? null,
                    dateTo: dateTo ?? null,
                }),
            },
        ],
    }),

    selectors({
        query: [
            (s) => [s.sessionId, s.dateRange],
            (
                sessionId: string,
                dateRange: { dateFrom: string | null; dateTo: string | null } | null
            ): DataTableNode => {
                const sessionQuery: SessionQuery = {
                    kind: NodeKind.SessionQuery,
                    sessionId,
                    includeSentiment: true,
                    dateRange: dateRange?.dateFrom
                        ? {
                              date_from: dateRange.dateFrom,
                              date_to: dateRange?.dateTo || undefined,
                          }
                        : undefined,
                }

                return {
                    kind: NodeKind.DataTableNode,
                    source: sessionQuery,
                }
            },
        ],

        breadcrumbs: [
            (s) => [s.sessionId, s.dateFilter],
            (sessionId: string, dateFilter: { dateFrom: string | null; dateTo: string | null }): Breadcrumb[] => {
                const sessionsUrl = urls.aiObservabilitySessions()
                const searchParams = router.values.searchParams
                const sessionsPath =
                    dateFilter?.dateFrom || dateFilter?.dateTo || Object.keys(searchParams).length > 0
                        ? `${sessionsUrl}?${new URLSearchParams({
                              ...searchParams,
                              ...(dateFilter?.dateFrom && { date_from: dateFilter.dateFrom }),
                              ...(dateFilter?.dateTo && { date_to: dateFilter.dateTo }),
                          }).toString()}`
                        : sessionsUrl
                return [
                    {
                        key: 'AIObservability',
                        name: 'AI observability',
                        path: urls.aiObservabilityDashboard(),
                        iconType: 'llm_analytics',
                    },
                    {
                        key: 'AIObservabilitySessions',
                        name: 'Sessions',
                        path: sessionsPath,
                        iconType: 'llm_analytics',
                    },
                    {
                        key: ['AIObservabilitySession', sessionId || ''],
                        name: sessionId,
                        iconType: 'llm_analytics',
                    },
                ]
            },
        ],
    }),

    urlToAction(({ actions, values }) => ({
        [urls.aiObservabilitySession(':id')]: ({ id }, { timestamp, date_from, date_to }) => {
            actions.setSessionId(id ?? '')
            if (timestamp) {
                actions.setDateRange(timestamp || null)
            } else if (date_from || date_to) {
                actions.setDateRange(date_from || null, date_to || null)
            } else if (values.dateRange?.dateFrom) {
                // Keep existing date range if no params provided
                actions.setDateRange(values.dateRange.dateFrom, values.dateRange.dateTo || null)
            } else if (values.dateFilter) {
                // Fall back to parent dateFilter when navigating without explicit date params
                actions.setDateRange(values.dateFilter.dateFrom, values.dateFilter.dateTo)
            }
        },
    })),
])
