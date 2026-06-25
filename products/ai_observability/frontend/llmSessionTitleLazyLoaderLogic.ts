import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { chunk } from 'lib/utils/arrays'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { escapeHogQLString } from '~/queries/utils'

import type { llmSessionTitleLazyLoaderLogicType } from './llmSessionTitleLazyLoaderLogicType'
import { resolveTitleFromInputs } from './sessionTitle'
import type { DateRangeFilter } from './types'
import { parsePartialJSON } from './utils'

const BATCH_MAX_SIZE = 100
// Cap per field. Titles only need the opening user message, so a small slice is
// plenty and keeps the ClickHouse aggregation state + network payload bounded.
const FIELD_TRUNCATE_CHARS = 1000
// Trace names are short labels; cap them tighter than the message payloads.
const TRACE_NAME_TRUNCATE_CHARS = 200
const SESSION_ID_MAX_LENGTH = 256

// We only need the opening user message, this method parses the head.
// A similar truncate-then-parse pattern exists in traceMessagesLazyLoaderLogic
function parseTruncatedJson(value: unknown): unknown {
    if (typeof value !== 'string' || value.length === 0) {
        return null
    }
    try {
        return JSON.parse(value)
    } catch {
        try {
            return parsePartialJSON(value)
        } catch {
            return null
        }
    }
}

// Per-session opening payloads collected from whichever table holds them.
interface SessionPayloads {
    inputState: unknown
    genInput: unknown
    traceName: string | null
}

// `dateFrom` is required (not nullable): the caller only builds this query once it has a lower
// bound, so the scan over the huge, otherwise-unbounded `events` table is never unbounded.
function eventsTableQuery(sessionIds: string, dateFrom: string, dateTo: string | null): HogQLQuery {
    return {
        kind: NodeKind.HogQLQuery,
        query: `
            SELECT
                properties.$ai_session_id AS session_id,
                argMinIf(
                    substringUTF8(toString(properties.$ai_input_state), 1, ${FIELD_TRUNCATE_CHARS}),
                    timestamp,
                    event = '$ai_trace' AND length(toString(properties.$ai_input_state)) > 0
                ) AS first_input_state,
                argMinIf(
                    substringUTF8(toString(properties.$ai_input), 1, ${FIELD_TRUNCATE_CHARS}),
                    timestamp,
                    event = '$ai_generation' AND length(toString(properties.$ai_input)) > 0
                ) AS first_gen_input,
                argMinIf(
                    substringUTF8(toString(properties.$ai_span_name), 1, ${TRACE_NAME_TRUNCATE_CHARS}),
                    timestamp,
                    event = '$ai_trace' AND length(toString(properties.$ai_span_name)) > 0
                ) AS first_trace_name
            FROM events
            WHERE event IN ('$ai_trace', '$ai_generation')
              AND properties.$ai_session_id IN (${sessionIds})
              AND {filters}
            GROUP BY session_id
        `,
        filters: {
            dateRange: {
                date_from: dateFrom,
                date_to: dateTo,
            },
        },
    }
}

function aiEventsTableQuery(sessionIds: string): HogQLQuery {
    return {
        kind: NodeKind.HogQLQuery,
        // Not time-bounded: `ai_events` carries a ~30-day TTL so it is inherently bounded
        // (unlike the shared `events` table), and the `{filters}` date placeholder targets the
        // events table. The bloom-filter skip index on session_id prunes the scan.
        query: `
            SELECT
                session_id,
                argMinIf(
                    substringUTF8(input_state, 1, ${FIELD_TRUNCATE_CHARS}),
                    timestamp,
                    event = '$ai_trace' AND length(input_state) > 0
                ) AS first_input_state,
                argMinIf(
                    substringUTF8(input, 1, ${FIELD_TRUNCATE_CHARS}),
                    timestamp,
                    event = '$ai_generation' AND length(input) > 0
                ) AS first_gen_input,
                argMinIf(
                    substringUTF8(span_name, 1, ${TRACE_NAME_TRUNCATE_CHARS}),
                    timestamp,
                    event = '$ai_trace' AND length(span_name) > 0
                ) AS first_trace_name
            FROM posthog.ai_events AS ai_events
            WHERE event IN ('$ai_trace', '$ai_generation')
              AND session_id IN (${sessionIds})
            GROUP BY session_id
        `,
    }
}

/**
 * Fetch opening-message payloads for a batch of sessions from both the shared
 * `events` table and the dedicated `ai_events` table, then resolve a title from
 * whichever has data.
 * Returns the resolved titles, or `null` if every source query failed (so the
 * caller can mark the batch failed rather than cache empty titles).
 */
async function fetchSessionTitles(
    batch: string[],
    dateRange?: DateRangeFilter
): Promise<Map<string, string | null> | null> {
    const sessionIds = batch.map((id) => escapeHogQLString(id)).join(',')

    const dateFrom = dateRange?.dateFrom
    const eventsQuery = dateFrom ? [api.query(eventsTableQuery(sessionIds, dateFrom, dateRange?.dateTo ?? null))] : []
    const settled = await Promise.allSettled([...eventsQuery, api.query(aiEventsTableQuery(sessionIds))])

    if (settled.every((r) => r.status === 'rejected')) {
        console.warn('Error loading session titles batch', settled)
        return null
    }

    // Merge across both sources: keep the first non-empty payload per session.
    // Keyed by a Map (not a plain object) so session ids that collide with object
    // prototype keys (e.g. `__proto__`, sourced from untrusted event data) are
    // treated as plain keys rather than reading or polluting Object.prototype.
    const payloads = new Map<string, SessionPayloads>()
    for (const result of settled) {
        if (result.status !== 'fulfilled') {
            continue
        }
        for (const row of result.value.results || []) {
            const [sessionId, firstInputState, firstGenInput, firstTraceName] = row as [
                string,
                unknown,
                unknown,
                unknown,
            ]
            if (!sessionId) {
                continue
            }
            let current = payloads.get(sessionId)
            if (!current) {
                current = { inputState: null, genInput: null, traceName: null }
                payloads.set(sessionId, current)
            }
            if (current.inputState == null) {
                current.inputState = parseTruncatedJson(firstInputState)
            }
            if (current.genInput == null) {
                current.genInput = parseTruncatedJson(firstGenInput)
            }
            if (current.traceName == null && typeof firstTraceName === 'string' && firstTraceName.length > 0) {
                current.traceName = firstTraceName
            }
        }
    }

    const titles = new Map<string, string | null>()
    for (const sessionId of batch) {
        const payload = payloads.get(sessionId)
        titles.set(
            sessionId,
            payload ? resolveTitleFromInputs(payload.inputState, payload.genInput, payload.traceName) : null
        )
    }
    return titles
}

/**
 * Lazily derives a human-readable title for each session, shared by the Sessions
 * list and the session detail hero. Both fetch by session id, time-bounded to the
 * viewed date range (the events table is huge, so the bound guards performance); the
 * title is the session's first turn within that range.
 */
export const llmSessionTitleLazyLoaderLogic = kea<llmSessionTitleLazyLoaderLogicType>([
    path(['products', 'ai_observability', 'frontend', 'llmSessionTitleLazyLoaderLogic']),

    actions({
        ensureSessionTitleLoaded: (sessionId: string, dateRange?: DateRangeFilter) => ({ sessionId, dateRange }),
        markSessionIdsLoading: (sessionIds: string[]) => ({ sessionIds }),
        loadSessionTitlesBatchSuccess: (titles: Map<string, string | null>, requestedSessionIds: string[]) => ({
            titles,
            requestedSessionIds,
        }),
        loadSessionTitlesBatchFailure: (requestedSessionIds: string[]) => ({ requestedSessionIds }),
    }),

    reducers({
        // Map keyed by session id. `undefined` (key absent) = not yet requested,
        // `null` = resolved with no usable title. A Map keeps untrusted session ids
        // (e.g. `__proto__`) from colliding with object prototype keys.
        titlesBySessionId: [
            new Map<string, string | null>(),
            {
                loadSessionTitlesBatchSuccess: (state, { titles, requestedSessionIds }) => {
                    const next = new Map(state)
                    for (const sessionId of requestedSessionIds) {
                        next.set(sessionId, titles.get(sessionId) ?? null)
                    }
                    return next
                },
                loadSessionTitlesBatchFailure: (state, { requestedSessionIds }) => {
                    const next = new Map(state)
                    for (const sessionId of requestedSessionIds) {
                        next.set(sessionId, null)
                    }
                    return next
                },
            },
        ],

        loadingSessionIds: [
            new Set<string>(),
            {
                markSessionIdsLoading: (state, { sessionIds }) => {
                    const next = new Set(state)
                    for (const sessionId of sessionIds) {
                        if (sessionId) {
                            next.add(sessionId)
                        }
                    }
                    return next
                },
                loadSessionTitlesBatchSuccess: (state, { requestedSessionIds }) => {
                    const next = new Set(state)
                    for (const sessionId of requestedSessionIds) {
                        next.delete(sessionId)
                    }
                    return next
                },
                loadSessionTitlesBatchFailure: (state, { requestedSessionIds }) => {
                    const next = new Set(state)
                    for (const sessionId of requestedSessionIds) {
                        next.delete(sessionId)
                    }
                    return next
                },
            },
        ],
    }),

    selectors({
        getSessionTitle: [
            (s) => [s.titlesBySessionId],
            (titlesBySessionId): ((sessionId: string) => string | null | undefined) => {
                return (sessionId: string) => titlesBySessionId.get(sessionId)
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        ensureSessionTitleLoaded: ({ sessionId, dateRange }) => {
            if (
                !sessionId ||
                sessionId.length > SESSION_ID_MAX_LENGTH ||
                values.titlesBySessionId.has(sessionId) ||
                values.loadingSessionIds.has(sessionId)
            ) {
                return
            }

            actions.markSessionIdsLoading([sessionId])

            const pending = cache.pendingSessionIds as Set<string>
            pending.add(sessionId)
            // All rows in one view share the same date range; keep the latest seen for the batch.
            if (dateRange) {
                cache.pendingDateRange = dateRange
            }

            if (cache.batchTimer) {
                return
            }

            cache.batchTimer = setTimeout(async () => {
                const requested = Array.from(pending)
                const dateRangeForBatch = cache.pendingDateRange as DateRangeFilter | undefined
                pending.clear()
                cache.pendingDateRange = undefined
                cache.batchTimer = null

                if (requested.length === 0) {
                    return
                }

                await Promise.allSettled(
                    chunk(requested, BATCH_MAX_SIZE).map(async (batch) => {
                        const titles = await fetchSessionTitles(batch, dateRangeForBatch)
                        if (titles) {
                            actions.loadSessionTitlesBatchSuccess(titles, batch)
                        } else {
                            actions.loadSessionTitlesBatchFailure(batch)
                        }
                    })
                )
            }, 0)
        },
    })),

    events(({ cache }) => ({
        afterMount: () => {
            cache.pendingSessionIds = new Set<string>()
            cache.pendingDateRange = undefined
            cache.batchTimer = null
        },
        beforeUnmount: () => {
            if (cache.batchTimer) {
                clearTimeout(cache.batchTimer)
                cache.batchTimer = null
            }
            ;(cache.pendingSessionIds as Set<string> | undefined)?.clear?.()
        },
    })),
])
