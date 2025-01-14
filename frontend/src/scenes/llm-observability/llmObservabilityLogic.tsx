import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { STALE_EVENT_SECONDS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { getTracesQuery } from 'scenes/llm-observability/queries'

import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import {
    BaseMathType,
    ChartDisplayType,
    EventDefinition,
    EventDefinitionType,
    HogQLMathType,
    PropertyMathType,
} from '~/types'

import type { llmObservabilityLogicType } from './llmObservabilityLogicType'

export const LLM_OBSERVABILITY_DATA_COLLECTION_NODE_ID = 'llm-observability-data'

const INITIAL_DATE_FROM = '-30d' as string | null
const INITIAL_DATE_TO = null as string | null

export interface QueryTile {
    title: string
    description?: string
    query: TrendsQuery
    layout?: {
        className?: string
    }
}

export enum LLMObservabilityTab {
    Dashboard = 'dashboard',
    Traces = 'traces',
}

const isDefinitionStale = (definition: EventDefinition): boolean => {
    const parsedLastSeen = definition.last_seen_at ? dayjs(definition.last_seen_at) : null
    return !!parsedLastSeen && dayjs().diff(parsedLastSeen, 'seconds') > STALE_EVENT_SECONDS
}

export const llmObservabilityLogic = kea<llmObservabilityLogicType>([
    path(['scenes', 'llm-observability', 'llmObservabilityLogic']),

    actions({
        setDates: (dateFrom: string | null, dateTo: string | null) => ({ dateFrom, dateTo }),
        setShouldFilterTestAccounts: (shouldFilterTestAccounts: boolean) => ({ shouldFilterTestAccounts }),
        setActiveTab: (activeTab: LLMObservabilityTab) => ({ activeTab }),
        loadMoreTraces: true,
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
        shouldFilterTestAccounts: [
            false,
            {
                setShouldFilterTestAccounts: (_, { shouldFilterTestAccounts }) => shouldFilterTestAccounts,
            },
        ],
        activeTab: [LLMObservabilityTab.Dashboard, { setActiveTab: (_, { activeTab }) => activeTab }],
        queryLimit: [30, { setQueryLimit: (_, { queryLimit }) => queryLimit + 30 }],
    }),

    selectors({
        tiles: [
            (s) => [s.dateFilter, s.shouldFilterTestAccounts],
            (dateFilter, shouldFilterTestAccounts): QueryTile[] => [
                {
                    title: 'Generative AI users',
                    description: 'To count users, set `distinct_id` in LLM tracking.',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                kind: NodeKind.EventsNode,
                                math: BaseMathType.UniqueUsers,
                            },
                        ],
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                },
                {
                    title: 'Traces',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                kind: NodeKind.EventsNode,
                                math: HogQLMathType.HogQL,
                                math_hogql: 'COUNT(DISTINCT properties.$ai_trace_id)',
                            },
                        ],
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                },
                {
                    title: 'Total cost (USD)',
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
                        trendsFilter: {
                            aggregationAxisPrefix: '$',
                            decimalPlaces: 4,
                            display: ChartDisplayType.BoldNumber,
                        },
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                },
                {
                    title: 'Cost per user (USD)',
                    description: "Average cost for each generative AI user active in the data point's period.",
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                math: PropertyMathType.Sum,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_total_cost_usd',
                            },
                            {
                                event: '$ai_generation',
                                kind: NodeKind.EventsNode,
                                math: BaseMathType.UniqueUsers,
                            },
                        ],
                        trendsFilter: {
                            formula: 'A / B',
                            aggregationAxisPrefix: '$',
                            decimalPlaces: 2,
                        },
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                },
                {
                    title: 'Cost by model (USD)',
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
                        breakdownFilter: {
                            breakdown_type: 'event',
                            breakdown: '$ai_model',
                        },
                        trendsFilter: {
                            aggregationAxisPrefix: '$',
                            decimalPlaces: 2,
                            display: ChartDisplayType.ActionsBarValue,
                            showValuesOnSeries: true,
                        },
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                },
                {
                    title: 'Generation calls',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                kind: NodeKind.EventsNode,
                            },
                        ],
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                },
                {
                    title: 'Generation latency by model (median)',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                math: PropertyMathType.Median,
                                kind: NodeKind.EventsNode,
                                math_property: '$ai_latency',
                            },
                        ],
                        breakdownFilter: {
                            breakdown: '$ai_model',
                        },
                        trendsFilter: {
                            aggregationAxisPostfix: ' s',
                            decimalPlaces: 3,
                            yAxisScaleType: 'log10',
                        },
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                },
                {
                    title: 'Generations by HTTP status',
                    query: {
                        kind: NodeKind.TrendsQuery,
                        series: [
                            {
                                event: '$ai_generation',
                                kind: NodeKind.EventsNode,
                            },
                        ],
                        breakdownFilter: {
                            breakdown: '$ai_http_status',
                        },
                        trendsFilter: {
                            display: ChartDisplayType.ActionsBarValue,
                        },
                        dateRange: { date_from: dateFilter.dateFrom, date_to: dateFilter.dateTo },
                        filterTestAccounts: shouldFilterTestAccounts,
                    },
                },
            ],
        ],
        query: [(s) => [s.queryLimit], (queryLimit) => getTracesQuery({ limit: queryLimit })],
    }),
    loaders({
        hasSentAiGenerationEvent: {
            __default: undefined as boolean | undefined,
            loadAIEventDefinition: async (): Promise<boolean> => {
                const aiGenerationDefinition = await api.eventDefinitions.list({
                    event_type: EventDefinitionType.Event,
                    search: '$ai_generation',
                })

                // no need to worry about pagination here, event names beginning with $ are reserved, and we're not
                // going to add enough reserved event names that match this search term to cause problems
                const definition = aiGenerationDefinition.results.find((r) => r.name === '$ai_generation')
                if (definition && !isDefinitionStale(definition)) {
                    return true
                }
                return false
            },
        },
    }),
    afterMount(({ actions }) => {
        actions.loadAIEventDefinition()
    }),
])
