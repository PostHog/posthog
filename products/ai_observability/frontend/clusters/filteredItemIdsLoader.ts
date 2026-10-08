import api from 'lib/api'

import { HogQLQueryString, hogql } from '~/queries/utils'
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
    scene: string
}

/**
 * A trace matches when any of its events matches. Clustering stores generation items as
 * `$ai_generation` event UUIDs, so they match on `uuid`, the same as cluster metrics.
 *
 * The run window bounds when the embeddings were written, and a trace's events come before its
 * embedding, so the lower bound starts 7 days before the window start. Seven days also covers
 * most manual summarization runs over an older window.
 */
function buildFilterQuery(
    level: ClusteringLevel,
    ids: string[],
    windowStart: string,
    windowEnd: string
): HogQLQueryString {
    if (level === 'generation') {
        return hogql`
            SELECT DISTINCT toString(uuid) AS item_id
            FROM events
            WHERE event = '$ai_generation'
                AND timestamp >= parseDateTimeBestEffort(${windowStart}) - INTERVAL 7 DAY
                AND timestamp <= parseDateTimeBestEffort(${windowEnd})
                AND uuid IN ${ids}
                AND {filters}
            LIMIT ${ids.length}
        `
    }
    return hogql`
        SELECT DISTINCT properties.$ai_trace_id AS item_id
        FROM events
        WHERE event IN ${TRACE_MEMBER_EVENTS}
            AND timestamp >= parseDateTimeBestEffort(${windowStart}) - INTERVAL 7 DAY
            AND timestamp <= parseDateTimeBestEffort(${windowEnd})
            AND properties.$ai_trace_id IN ${ids}
            AND {filters}
        LIMIT ${ids.length}
    `
}

function toItemIdSet(results: unknown[] | undefined): Set<string> {
    const matched = new Set<string>()
    for (const row of results || []) {
        const id = (row as unknown[])[0]
        if (typeof id === 'string' && id) {
            matched.add(id)
        }
    }
    return matched
}

/**
 * Subset of `itemIds` whose events match the active filters. Null means "show everything": no filters
 * are on, the level carries no person data, or the run is too large for one query.
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

    // Trace ids are free-form strings, and the `hogql` tag escapes them. Generation ids go into a
    // comparison with the uuid column, where one value that is not a UUID fails the whole query.
    // So drop generation ids with characters a UUID never has.
    const safeIds = level === 'generation' ? itemIds.filter((id) => SAFE_ID_RE.test(id)) : itemIds.filter(Boolean)
    if (safeIds.length === 0) {
        return new Set<string>()
    }

    // Above the row cap the query would silently miss matches, so skip filtering instead.
    if (safeIds.length > FILTER_QUERY_MAX_ROWS) {
        console.warn(
            `Skipping cluster filters: ${safeIds.length} items exceed the ${FILTER_QUERY_MAX_ROWS}-row cap for filter queries.`
        )
        return null
    }

    const response = await api.queryHogQL(
        buildFilterQuery(level, safeIds, windowStart, windowEnd),
        { productKey: 'llm_analytics', scene },
        {
            queryParams: {
                filters: { properties: propertyFilters, filterTestAccounts },
                // Window bounds are in UTC (from the backend), so compare timestamps in UTC
                modifiers: { convertToProjectTimezone: false },
            },
        }
    )

    return toItemIdSet(response.results)
}
