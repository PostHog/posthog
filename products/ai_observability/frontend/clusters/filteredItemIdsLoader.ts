import api from 'lib/api'

import { hogql } from '~/queries/utils'
import { AnyPropertyFilter } from '~/types'

import { FILTER_QUERY_MAX_ROWS, SAFE_ID_RE, TRACE_MEMBER_EVENTS } from './constants'
import { ClusteringLevel } from './types'

export interface FilterMatchedItemIdsParams {
    /** Cluster item ids to test: trace ids at trace level, `$ai_generation` event UUIDs at generation level. */
    itemIds: string[]
    level: ClusteringLevel
    windowStart: string
    windowEnd: string
    propertyFilters: AnyPropertyFilter[]
    filterTestAccounts: boolean
    /** ClickHouse query tag, so the scene that issued the query stays visible in query logs. */
    scene: string
}

/**
 * Subset of `itemIds` whose events match the active property filters and test-account toggle.
 *
 * Returns null when no filtering applies, which callers read as "show everything": no filters are
 * on, the level carries no person data, or the run is too large for one query.
 */
export async function loadFilterMatchedItemIds({
    itemIds,
    level,
    windowStart,
    windowEnd,
    propertyFilters,
    filterTestAccounts,
    scene,
}: FilterMatchedItemIdsParams): Promise<Set<string> | null> {
    if (propertyFilters.length === 0 && !filterTestAccounts) {
        return null
    }

    // Eval clusters key on $ai_evaluation event UUIDs, which carry none of the person or cohort
    // fields these filters target. The eval-specific filter bar handles those.
    if (level === 'evaluation') {
        return null
    }

    const safeIds = itemIds.filter((id) => SAFE_ID_RE.test(id))
    if (safeIds.length === 0) {
        return new Set<string>()
    }

    // Above the row cap we would silently miss matches and render a misleading partial result.
    // Skip filtering instead and warn — a later change can paginate through offsets if real runs
    // start to hit this.
    if (safeIds.length > FILTER_QUERY_MAX_ROWS) {
        console.warn(
            `Skipping cluster filters: ${safeIds.length} items exceed the ${FILTER_QUERY_MAX_ROWS}-row cap for filter queries.`
        )
        return null
    }

    // A trace matches when any of its events matches, so test every event that belongs to a trace.
    // Reading only `$ai_generation` dropped every clustered trace with no generation in the window.
    // Generation items are `$ai_generation` event UUIDs — the SDK does not set `$ai_generation_id`
    // on the event, so match the `uuid` column the way cluster metrics do.
    const response = await api.queryHogQL(
        level === 'generation'
            ? hogql`
                SELECT DISTINCT toString(uuid) AS item_id
                FROM events
                WHERE event = '$ai_generation'
                    AND timestamp >= parseDateTimeBestEffort(${windowStart})
                    AND timestamp <= parseDateTimeBestEffort(${windowEnd})
                    AND uuid IN ${safeIds}
                    AND {filters}
                LIMIT ${safeIds.length}
            `
            : hogql`
                SELECT DISTINCT properties.$ai_trace_id AS item_id
                FROM events
                WHERE event IN ${TRACE_MEMBER_EVENTS}
                    AND timestamp >= parseDateTimeBestEffort(${windowStart})
                    AND timestamp <= parseDateTimeBestEffort(${windowEnd})
                    AND properties.$ai_trace_id IN ${safeIds}
                    AND {filters}
                LIMIT ${safeIds.length}
            `,
        { productKey: 'llm_analytics', scene },
        {
            queryParams: {
                // `{filters}` turns the user's property filters and the test-account toggle into
                // the same expressions an insight builds, including cohorts and person properties.
                filters: { properties: propertyFilters, filterTestAccounts },
                // Window bounds are in UTC (from the backend), so compare timestamps in UTC
                modifiers: { convertToProjectTimezone: false },
            },
        }
    )

    const matched = new Set<string>()
    for (const row of response.results || []) {
        const id = (row as unknown[])[0]
        if (typeof id === 'string' && id) {
            matched.add(id)
        }
    }
    return matched
}
