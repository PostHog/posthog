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
        setLoading: (sessionId: string, loading: boolean) => ({ sessionId, loading }),
        setProgress: (sessionId: string, progress: SummarizationProgress | null) => ({ sessionId, progress }),
        setSummary: (sessionId: string, summary: SessionSummaryContent | null) => ({ sessionId, summary }),
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
            },
        ],
        progressBySessionId: [
            {} as Record<string, SummarizationProgress | null>,
            {
                startSummarization: (state, { sessionId }) => ({ ...state, [sessionId]: null }),
                setProgress: (state, { sessionId, progress }) => ({ ...state, [sessionId]: progress }),
                setSummary: (state, { sessionId }) => ({ ...state, [sessionId]: null }),
            },
        ],
        summaryBySessionId: [
            {} as Record<string, SessionSummaryContent | null>,
            {
                setSummary: (state, { sessionId, summary }) => ({ ...state, [sessionId]: summary }),
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

            const timeout = window.setTimeout(() => {
                actions.setLoading(sessionId, false)
            }, SUMMARIZATION_TIMEOUT_MS)

            try {
                const response = await api.recordings.summarizeStream(sessionId)
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
                                actions.setLoading(sessionId, false)
                                return
                            }
                            if (event === 'session-summary-progress') {
                                actions.setProgress(sessionId, JSON.parse(data))
                                return
                            }
                            const parsedData = JSON.parse(data)
                            if (parsedData) {
                                actions.setSummary(sessionId, parsedData)
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
                if (err instanceof ApiError) {
                    lemonToast.error(err.message)
                    actions.setLoading(sessionId, false)
                } else {
                    posthog.captureException(err)
                    actions.setLoading(sessionId, false)
                }
            } finally {
                window.clearTimeout(timeout)
                inFlightSessionIds.delete(sessionId)
            }
        },
    })),
])
