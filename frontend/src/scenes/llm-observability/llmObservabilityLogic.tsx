import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { STALE_EVENT_SECONDS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import { NodeKind, TrendsQuery } from '~/queries/schema/schema-general'
import { EventDefinition, EventDefinitionType, PropertyMathType } from '~/types'

import type { llmObservabilityLogicType } from './llmObservabilityLogicType'

export const LLM_OBSERVABILITY_DATA_COLLECTION_NODE_ID = 'llm-observability-data'

const INITIAL_DATE_FROM = '-30d' as string | null
const INITIAL_DATE_TO = null as string | null

export interface QueryTile {
    title: string
    query: TrendsQuery
    layout?: {
        className?: string
    }
}

const isDefinitionStale = (definition: EventDefinition): boolean => {
    const parsedLastSeen = definition.last_seen_at ? dayjs(definition.last_seen_at) : null
    return !!parsedLastSeen && dayjs().diff(parsedLastSeen, 'seconds') > STALE_EVENT_SECONDS
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
    loaders({
        hasSentAiGenerationEvent: {
            __default: undefined as boolean | undefined,
            loadAIEventDefinition: async (): Promise<boolean | undefined> => {
                const aiGenerationDefinition = await api.eventDefinitions.list({
                    event_type: EventDefinitionType.Event,
                    search: '$ai_generation',
                })

                // no need to worry about pagination here, event names beginning with $ are reserved, and we're not
                // going to add enough reserved event names that match this search term to cause problems
                const definition = aiGenerationDefinition.results.find((r) => r.name === '$ai_generation')
                if (definition) {
                    if (!isDefinitionStale(definition)) {
                        return true
                    }
                    return false
                }
                return undefined
            },
        },
    }),
    afterMount(({ actions }) => {
        actions.loadAIEventDefinition()
    }),
])
