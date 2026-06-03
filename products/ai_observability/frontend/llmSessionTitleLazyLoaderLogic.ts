import { actions, events, kea, listeners, path, reducers, selectors } from 'kea'

import api from 'lib/api'
import { chunk } from 'lib/utils'

import { HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { escapeHogQLString } from '~/queries/utils'

import type { llmSessionTitleLazyLoaderLogicType } from './llmSessionTitleLazyLoaderLogicType'
import { resolveTitleFromInputs } from './sessionTitle'
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

function eventsTableQuery(sessionIds: string): HogQLQuery {
    return {
        kind: NodeKind.HogQLQuery,
        // No timerange limit in the query, since (1) the bloom-filter skip index on
        // session_id (HogQL maps properties.$ai_session_id -> mat_$ai_session_id) prunes
        // the scan to matching granules, and (2) argMin needs the session's true first turn
        query: `
            SELECT
                properties.$ai_session_id AS session_id,
                argMinIf(
                    substring(toString(properties.$ai_input_state), 1, ${FIELD_TRUNCATE_CHARS}),
                    timestamp,
                    event = '$ai_trace' AND length(toString(properties.$ai_input_state)) > 0
                ) AS first_input_state,
                argMinIf(
                    substring(toString(properties.$ai_input), 1, ${FIELD_TRUNCATE_CHARS}),
                    timestamp,
                    event = '$ai_generation' AND length(toString(properties.$ai_input)) > 0
                ) AS first_gen_input,
                argMinIf(
                    substring(toString(properties.$ai_span_name), 1, ${TRACE_NAME_TRUNCATE_CHARS}),
                    timestamp,
                    event = '$ai_trace' AND length(toString(properties.$ai_span_name)) > 0
                ) AS first_trace_name
            FROM events
            WHERE event IN ('$ai_trace', '$ai_generation')
              AND properties.$ai_session_id IN (${sessionIds})
            GROUP BY session_id
        `,
    }
}

function aiEventsTableQuery(sessionIds: string): HogQLQuery {
    return {
        kind: NodeKind.HogQLQuery,
        // No time bound since (1) ai_events has a bloom-filter skip index on session_id
        // (and a 30-day TTL), and (2) argMin needs the session's true first turn
        query: `
            SELECT
                session_id,
                argMinIf(
                    substring(input_state, 1, ${FIELD_TRUNCATE_CHARS}),
                    timestamp,
                    event = '$ai_trace' AND length(input_state) > 0
                ) AS first_input_state,
                argMinIf(
                    substring(input, 1, ${FIELD_TRUNCATE_CHARS}),
                    timestamp,
                    event = '$ai_generation' AND length(input) > 0
                ) AS first_gen_input,
                argMinIf(
                    substring(span_name, 1, ${TRACE_NAME_TRUNCATE_CHARS}),
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
async function fetchSessionTitles(batch: string[]): Promise<Record<string, string | null> | null> {
    const sessionIds = batch.map((id) => escapeHogQLString(id)).join(',')

    const settled = await Promise.allSettled([
        api.query(eventsTableQuery(sessionIds)),
        api.query(aiEventsTableQuery(sessionIds)),
    ])

    if (settled.every((r) => r.status === 'rejected')) {
        console.warn('Error loading session titles batch', settled)
        return null
    }

    // Merge across both sources: keep the first non-empty payload per session.
    const payloads: Record<string, SessionPayloads> = {}
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
            const current =
                payloads[sessionId] ?? (payloads[sessionId] = { inputState: null, genInput: null, traceName: null })
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

    const titles: Record<string, string | null> = {}
    for (const sessionId of batch) {
        const payload = payloads[sessionId]
        titles[sessionId] = payload
            ? resolveTitleFromInputs(payload.inputState, payload.genInput, payload.traceName)
            : null
    }
    return titles
}

/**
 * Lazily derives a human-readable title for each session, shared by the Sessions
 * list and the session detail hero. Both fetch by session id (not the page date
 * window), so the title reflects the session's opening turn
 */
export const llmSessionTitleLazyLoaderLogic = kea<llmSessionTitleLazyLoaderLogicType>([
    path(['products', 'ai_observability', 'frontend', 'llmSessionTitleLazyLoaderLogic']),

    actions({
        ensureSessionTitleLoaded: (sessionId: string) => ({ sessionId }),
        markSessionIdsLoading: (sessionIds: string[]) => ({ sessionIds }),
        loadSessionTitlesBatchSuccess: (titles: Record<string, string | null>, requestedSessionIds: string[]) => ({
            titles,
            requestedSessionIds,
        }),
        loadSessionTitlesBatchFailure: (requestedSessionIds: string[]) => ({ requestedSessionIds }),
    }),

    reducers({
        // `undefined` = not yet requested, `null` = resolved with no usable title.
        titlesBySessionId: [
            {} as Record<string, string | null>,
            {
                loadSessionTitlesBatchSuccess: (state, { titles, requestedSessionIds }) => {
                    const next = { ...state }
                    for (const sessionId of requestedSessionIds) {
                        next[sessionId] = titles[sessionId] ?? null
                    }
                    return next
                },
                loadSessionTitlesBatchFailure: (state, { requestedSessionIds }) => {
                    const next = { ...state }
                    for (const sessionId of requestedSessionIds) {
                        next[sessionId] = null
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
                return (sessionId: string) => titlesBySessionId[sessionId]
            },
        ],
    }),

    listeners(({ actions, values, cache }) => ({
        ensureSessionTitleLoaded: ({ sessionId }) => {
            if (
                !sessionId ||
                sessionId.length > SESSION_ID_MAX_LENGTH ||
                values.titlesBySessionId[sessionId] !== undefined ||
                values.loadingSessionIds.has(sessionId)
            ) {
                return
            }

            actions.markSessionIdsLoading([sessionId])

            const pending = cache.pendingSessionIds as Set<string>
            pending.add(sessionId)

            if (cache.batchTimer) {
                return
            }

            cache.batchTimer = setTimeout(async () => {
                const requested = Array.from(pending)
                pending.clear()
                cache.batchTimer = null

                if (requested.length === 0) {
                    return
                }

                await Promise.allSettled(
                    chunk(requested, BATCH_MAX_SIZE).map(async (batch) => {
                        const titles = await fetchSessionTitles(batch)
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
