import { createParser } from 'eventsource-parser'
import { actions, kea, listeners, path, reducers } from 'kea'
import posthog from 'posthog-js'

import api, { ApiError } from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { SessionRecordingType } from '~/types'

import type { sessionSummaryProgressLogicType } from './sessionSummaryProgressLogicType'
import { SessionSummaryContent, SummarizationProgress } from './types'

// Give up waiting after 10 minutes. The workflow may still complete later; if
// so the summary will show up next time the user opens this recording.
const SUMMARIZATION_TIMEOUT_MS = 10 * 60 * 1000

// Tracks which sessions currently have an open SSE reader, so a repeat
// `startSummarization` dispatch doesn't spawn a parallel reader against the
// same backend workflow.
const inFlightSessionIds = new Set<string>()

// Per-session AbortControllers so `cancelSummarization` can tear down the SSE
// fetch (and its underlying reader) for a specific session. The backend Temporal workflow is aborted.
const abortControllersBySessionId = new Map<string, AbortController>()

// Sessions whose previous summarization was user-cancelled. The next
// `startSummarization` for these sessions sends `force_restart=true` so the
// backend uses TERMINATE_EXISTING and cleanly preempts any workflow still
// finishing its CANCEL_REQUESTED -> CANCELLED transition. The flag is consumed
// (deleted) by the next start so a subsequent click without an intervening
// cancel falls back to the default attach-to-existing behavior.
const cancelledSessionIds = new Set<string>()

/**
 * Singleton store for in-flight session summarization state, keyed by session id.
 *
 * Exists so that progress survives navigation away from a recording and back —
 * the per-player `playerMetaLogic` is keyed by sessionRecordingId and gets torn
 * down on unmount, which was wiping the loading flag and progress reducer
 * mid-stream and making the "Use AI to summarise" button reappear.
 */
export const sessionSummaryProgressLogic = kea<sessionSummaryProgressLogicType>([
    path(['scenes', 'session-recordings', 'player', 'player-meta', 'sessionSummaryProgressLogic']),
    actions({
        startSummarization: (sessionId: SessionRecordingType['id']) => ({ sessionId }),
        cancelSummarization: (sessionId: SessionRecordingType['id']) => ({ sessionId }),
        setLoading: (sessionId: string, loading: boolean) => ({ sessionId, loading }),
        setProgress: (sessionId: string, progress: SummarizationProgress | null) => ({ sessionId, progress }),
        setSummary: (sessionId: string, summary: SessionSummaryContent | null, summaryId: string | null = null) => ({
            sessionId,
            summary,
            summaryId,
        }),
        setError: (sessionId: string, error: string | null) => ({ sessionId, error }),
        markFeedbackGiven: (sessionId: string) => ({ sessionId }),
        setSummaryOpen: (sessionId: string, open: boolean) => ({ sessionId, open }),
    }),
    reducers({
        loadingBySessionId: [
            {} as Record<string, boolean>,
            {
                startSummarization: (state, { sessionId }) => ({ ...state, [sessionId]: true }),
                setLoading: (state, { sessionId, loading }) => ({ ...state, [sessionId]: loading }),
                setSummary: (state, { sessionId }) => ({ ...state, [sessionId]: false }),
                setError: (state, { sessionId }) => ({ ...state, [sessionId]: false }),
                cancelSummarization: (state, { sessionId }) => ({ ...state, [sessionId]: false }),
            },
        ],
        progressBySessionId: [
            {} as Record<string, SummarizationProgress | null>,
            {
                startSummarization: (state, { sessionId }) => ({ ...state, [sessionId]: null }),
                setProgress: (state, { sessionId, progress }) => ({ ...state, [sessionId]: progress }),
                setSummary: (state, { sessionId }) => ({ ...state, [sessionId]: null }),
                cancelSummarization: (state, { sessionId }) => ({ ...state, [sessionId]: null }),
            },
        ],
        summaryBySessionId: [
            {} as Record<string, SessionSummaryContent | null>,
            {
                setSummary: (state, { sessionId, summary }) => ({ ...state, [sessionId]: summary }),
            },
        ],
        summaryIdBySessionId: [
            {} as Record<string, string | null>,
            {
                setSummary: (state, { sessionId, summaryId }) => ({ ...state, [sessionId]: summaryId }),
            },
        ],
        errorBySessionId: [
            {} as Record<string, string | null>,
            {
                startSummarization: (state, { sessionId }) => ({ ...state, [sessionId]: null }),
                setError: (state, { sessionId, error }) => ({ ...state, [sessionId]: error }),
                setSummary: (state, { sessionId }) => ({ ...state, [sessionId]: null }),
            },
        ],
        retryStateBySessionId: [
            {} as Record<string, { maxStep: number; hasRetried: boolean }>,
            {
                startSummarization: (state, { sessionId }) => ({
                    ...state,
                    [sessionId]: { maxStep: 0, hasRetried: false },
                }),
                setSummary: (state, { sessionId }) => ({
                    ...state,
                    [sessionId]: { maxStep: 0, hasRetried: false },
                }),
                setProgress: (state, { sessionId, progress }) => {
                    if (!progress) {
                        return state
                    }
                    const existing = state[sessionId] ?? { maxStep: 0, hasRetried: false }
                    return {
                        ...state,
                        [sessionId]: {
                            maxStep: Math.max(existing.maxStep, progress.step),
                            hasRetried: existing.hasRetried || progress.step < existing.maxStep,
                        },
                    }
                },
            },
        ],
        feedbackBySessionId: [
            {} as Record<string, boolean>,
            {
                markFeedbackGiven: (state, { sessionId }) => ({ ...state, [sessionId]: true }),
            },
        ],
        openBySessionId: [
            {} as Record<string, boolean>,
            {
                setSummaryOpen: (state, { sessionId, open }) => ({ ...state, [sessionId]: open }),
                startSummarization: (state, { sessionId }) => ({ ...state, [sessionId]: true }),
                setSummary: (state, { sessionId, summary }) => (summary ? { ...state, [sessionId]: true } : state),
            },
        ],
    }),
    listeners(({ actions }) => ({
        startSummarization: async ({ sessionId }) => {
            if (inFlightSessionIds.has(sessionId)) {
                return
            }
            inFlightSessionIds.add(sessionId)

            const controller = new AbortController()
            abortControllersBySessionId.set(sessionId, controller)

            // Consume the post-cancel flag exactly once so a follow-up click
            // without an intervening cancel uses the default attach-to-existing
            // behavior on the backend.
            const forceRestart = cancelledSessionIds.delete(sessionId)

            const timeout = window.setTimeout(() => {
                actions.setLoading(sessionId, false)
            }, SUMMARIZATION_TIMEOUT_MS)

            try {
                const response = await api.recordings.summarizeStream(sessionId, {
                    signal: controller.signal,
                    forceRestart,
                })
                const reader = response.body?.getReader()
                if (!reader) {
                    throw new Error('No reader available')
                }
                const decoder = new TextDecoder()
                const parser = createParser({
                    onEvent: ({ event, data }) => {
                        try {
                            if (event === 'session-summary-error') {
                                lemonToast.error(data)
                                actions.setError(sessionId, data)
                                return
                            }
                            if (event === 'session-summary-progress') {
                                actions.setProgress(sessionId, JSON.parse(data))
                                return
                            }
                            const parsedData = JSON.parse(data)
                            if (parsedData?.summary) {
                                actions.setSummary(sessionId, parsedData.summary, parsedData.id ?? null)
                            }
                        } catch {
                            // Don't handle errors as we can afford to fail some chunks silently.
                            // However, there should not be any unparseable chunks coming from the server as they are validated before being sent.
                        }
                    },
                })
                while (true) {
                    const { done, value } = await reader.read()
                    if (done) {
                        break
                    }
                    parser.feed(decoder.decode(value))
                }
            } catch (err) {
                // User-initiated cancellation: surface no error, keep state cleared by the cancel listener.
                if (controller.signal.aborted || (err instanceof DOMException && err.name === 'AbortError')) {
                    return
                }
                if (err instanceof ApiError) {
                    lemonToast.error(err.message)
                    actions.setLoading(sessionId, false)
                } else {
                    posthog.captureException(err)
                    actions.setLoading(sessionId, false)
                }
            } finally {
                window.clearTimeout(timeout)
                // Only clean up entries that still belong to *this* run. After a
                // cancel, the synchronous abort schedules our reader's rejection
                // as a microtask; if startSummarization is invoked again before
                // that microtask runs (tests, programmatic callers), the new
                // run's controller and in-flight entry will already be in the
                // maps. Identity-checking the controller prevents the old
                // listener from evicting them.
                if (abortControllersBySessionId.get(sessionId) === controller) {
                    abortControllersBySessionId.delete(sessionId)
                    inFlightSessionIds.delete(sessionId)
                }
            }
        },
        cancelSummarization: ({ sessionId }) => {
            // Tear down local state first so late-arriving SSE events from the
            // already-buffered stream can't repopulate progress/summary after
            // the user clicked cancel. Also frees the in-flight slot
            // immediately so a subsequent Summarize click isn't dropped by the
            // duplicate-start guard.
            const controller = abortControllersBySessionId.get(sessionId)
            abortControllersBySessionId.delete(sessionId)
            inFlightSessionIds.delete(sessionId)
            // Mark this session so the next startSummarization sends
            // ``force_restart=true``. The backend then uses TERMINATE_EXISTING
            // to atomically preempt any workflow that's still mid-cancellation.
            cancelledSessionIds.add(sessionId)
            controller?.abort()

            // Fire-and-forget the backend cancel — don't block UI on the
            // Temporal RPC. The workflow may have already finished or never
            // started; both are fine.
            void api.recordings.cancelSummarize(sessionId).catch((err) => {
                posthog.captureException(err)
            })
        },
    })),
])
