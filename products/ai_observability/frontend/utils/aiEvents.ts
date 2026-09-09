import api from 'lib/api'
import { isDefinitionStale } from 'lib/utils/definitions'

import { HogQLQuery, NodeKind, ProductKey } from '~/queries/schema/schema-general'
import { hogql } from '~/queries/utils'
import { EventDefinitionType } from '~/types'

// Keep in sync with the `setupProbe` in ../../manifest.tsx (the boot-time approximation of this check).
const AI_EVENT_NAMES = ['$ai_generation', '$ai_trace', '$ai_span', '$ai_embedding']

// Use a longer staleness window than the global default so orgs that ingested AI events
// in the past, paused, and have since resumed still land on the dashboard rather than the
// onboarding screen.
const AI_STALE_EVENT_DAYS = 90
const AI_STALE_EVENT_SECONDS = AI_STALE_EVENT_DAYS * 24 * 60 * 60

/**
 * Checks if the team has sent any AI events. Answers `null` when the check could not run.
 *
 * Uses a two-tier approach:
 * 1. Fast path: Check EventDefinition table (Postgres)
 * 2. Fallback: Query ClickHouse directly for recent events (for new users)
 */
export async function hasRecentAIEvents(): Promise<boolean | null> {
    try {
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
    } catch {
        // Every caller re-runs this check on a timer, so a rejection here reaches error tracking
        // once per tick for as long as the tab stays open. One user behind a blocked connection,
        // or on a project they cannot read, then files hundreds of issues in a day. The stack
        // cannot say which of the two requests failed either, while `client_request_failure`
        // already records both with their status and pathname. So answer "cannot tell" and let
        // the caller decide what to show.
        return null
    }
}

let seenAiEvents = false
let inFlightAiEventsCheck: Promise<boolean> | null = null

async function runAiEventsCheck(): Promise<boolean> {
    try {
        // An unanswerable check reads as "not seen yet"; the poll retries on its next tick.
        if (await hasRecentAIEvents()) {
            seenAiEvents = true
        }
        return seenAiEvents
    } finally {
        inFlightAiEventsCheck = null
    }
}

/**
 * Shares one in-flight check and caches a hit, so the several install-step components polling
 * at once run at most one ClickHouse probe per tick. The query runs against the current project,
 * and switching projects reloads the page, so the cache is honest for a whole page load.
 */
export function pollRecentAIEvents(): Promise<boolean> {
    if (seenAiEvents) {
        return Promise.resolve(true)
    }
    inFlightAiEventsCheck ??= runAiEventsCheck()
    return inFlightAiEventsCheck
}
