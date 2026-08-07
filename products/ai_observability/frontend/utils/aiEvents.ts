import api from 'lib/api'
import { isDefinitionStale } from 'lib/utils/definitions'

import { HogQLQuery, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { EventDefinitionType } from '~/types'

// Match the whole `$ai_*` event family, not a hand-picked subset. A project sending only
// `$ai_evaluation`, `$ai_metric`, or `$ai_feedback` is still instrumented and must land on the
// dashboard rather than the onboarding screen.
const AI_EVENT_PREFIX = '$ai_'

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
        search: AI_EVENT_PREFIX,
    })

    const validDefinition = aiEventDefinitions?.results?.find(
        (r) => r.name.startsWith(AI_EVENT_PREFIX) && !isDefinitionStale(r, AI_STALE_EVENT_SECONDS)
    )

    if (validDefinition) {
        return true
    }

    // Fallback: query ClickHouse directly for recent events (new users). Use the same window as
    // the staleness rule above so the two paths agree on what "recently instrumented" means.
    const response = await api.query<HogQLQuery>(
        {
            kind: NodeKind.HogQLQuery,
            query: hogql`SELECT 1 FROM events WHERE event LIKE '$ai_%' AND timestamp > now() - toIntervalDay(${AI_STALE_EVENT_DAYS}) LIMIT 1`,
            tags: { productKey: ProductKey.AI_OBSERVABILITY },
        },
        { refresh: 'force_blocking' }
    )

    return (response.results?.length ?? 0) > 0
}
