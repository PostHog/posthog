import api from 'lib/api'
import { isDefinitionStale } from 'lib/utils/definitions'

import { HogQLQuery, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { EventDefinitionType } from '~/types'

const AI_EVENT_NAMES = ['$ai_generation', '$ai_trace', '$ai_span', '$ai_embedding']

// Use a longer staleness window than the global default so orgs that ingested AI events
// in the past, paused, and have since resumed still land on the dashboard rather than the
// onboarding screen.
const AI_STALE_EVENT_DAYS = 90
const AI_STALE_EVENT_SECONDS = AI_STALE_EVENT_DAYS * 24 * 60 * 60

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

    const validDefinition = aiEventDefinitions?.results?.find(
        (r) => AI_EVENT_NAMES.includes(r.name) && !isDefinitionStale(r, AI_STALE_EVENT_SECONDS)
    )

    if (validDefinition) {
        return true
    }

    // Fallback: query ClickHouse directly for recent events (new users)
    const response = await api.query<HogQLQuery>(
        {
            kind: NodeKind.HogQLQuery,
            query: hogql`SELECT 1 FROM events WHERE event IN ${[...AI_EVENT_NAMES]} AND timestamp > now() - INTERVAL 12 HOUR LIMIT 1`,
            tags: { productKey: ProductKey.AI_OBSERVABILITY },
        },
        { refresh: 'force_blocking' }
    )

    return (response.results?.length ?? 0) > 0
}
