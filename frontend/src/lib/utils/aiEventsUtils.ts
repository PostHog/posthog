import api from 'lib/api'

import { HogQLQuery, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { EventDefinitionType } from '~/types'

import { isDefinitionStale } from './definitions'

export const AI_EVENT_NAMES = ['$ai_generation', '$ai_trace', '$ai_span', '$ai_embedding']

/**
 * Checks if the team has sent any AI events.
 *
 * Uses a two-tier approach:
 * 1. Fast path: Check EventDefinition table (Postgres)
 * 2. Fallback: Query ClickHouse directly for recent events (for new users)
 */
export async function hasRecentAIEvents(): Promise<boolean> {
    // Fast path: check EventDefinition (works for most existing users)
    const aiEventDefinitions = await api.eventDefinitions.list({
        event_type: EventDefinitionType.Event,
        search: '$ai_',
    })

    const validDefinition = aiEventDefinitions.results.find(
        (r) => AI_EVENT_NAMES.includes(r.name) && !isDefinitionStale(r)
    )

    if (validDefinition) {
        return true
    }

    // Fallback: query ClickHouse directly for recent events (new users)
    const response = await api.query<HogQLQuery>(
        {
            kind: NodeKind.HogQLQuery,
            query: hogql`SELECT 1 FROM events WHERE event IN ${[...AI_EVENT_NAMES]} AND timestamp > now() - INTERVAL 3 HOUR LIMIT 1`,
            tags: { productKey: ProductKey.LLM_ANALYTICS },
        },
        { refresh: 'force_blocking' }
    )

    return (response.results?.length ?? 0) > 0
}
