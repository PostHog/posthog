import { actions, kea, path, reducers, selectors } from 'kea'

import { NodeKind, TrendsQuery } from '~/queries/schema'
import { PropertyMathType } from '~/types'

import type { llmObservabilityLogicType } from './llmObservabilityLogicType'

export const LLM_OBSERVABILITY_DATA_COLLECTION_NODE_ID = 'llm-observability-data'

const INITIAL_DATE_FROM = '-24h' as string | null
const INITIAL_DATE_TO = null as string | null

export interface QueryTile {
    title: string
    query: TrendsQuery
    layout?: {
        className?: string
    }
}

export const llmObservabilityLogic = kea<llmObservabilityLogicType>([
    path(['scenes', 'llm-observability', 'llmObservabilityLogic']),

    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
    }),

    reducers({
        dateFilter: [
            {
                dateFrom: INITIAL_DATE_FROM,
                dateTo: INITIAL_DATE_TO,
            },
            {
                setDates: (_, { dateFrom, dateTo }) => ({ dateFrom, dateTo }),
            },
        ],
    }),

    selectors({
        tiles: [
            (s) => [s.dateFilter],
            (dateFilter): QueryTile[] => [
                {
                    title: 'LLM generations',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                kind: NodeKind.EventsNode,
                            },
                        ],
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                    },
                },
                {
                    title: 'LLM costs (USD)',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                math: PropertyMathType.Sum,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_total_cost_usd',
                            },
                        ],
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                    },
                },
                {
                    title: 'Average latency (ms)',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                math: PropertyMathType.Average,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_latency',
                            },
                        ],
                        breakdownFilter: {
                            breakdown: '$ai_model',
                        },
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                    },
                },
            ],
        ],
    }),
])
