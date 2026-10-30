import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { preflightLogic } from 'lib/logic/preflightLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { Region } from '~/types'

import { type MessageRatingOrNull, messageRatingsLogic } from 'products/posthog_ai/frontend/api/logics'

import { maxThreadLogic } from '../maxThreadLogic'
import { useTraceId } from '../TraceIdContext'

/**
 * The rating and free-text feedback of one LangGraph answer, keyed by its trace. Both skins of
 * `SuccessActions` read it, so the `$ai_metric` and `$ai_feedback` events stay the same whichever is on.
 */
export function useAnswerRating(): {
    traceId: string | null
    rating: MessageRatingOrNull
    submitRating: (newRating: 'good' | 'bad') => void
    feedback: string
    setFeedback: (feedback: string) => void
    feedbackInputStatus: 'hidden' | 'pending' | 'submitted'
    closeFeedback: () => void
    submitFeedback: () => void
    traceUrl: string | null
} {
    const { traceId: logicTraceId } = useValues(maxThreadLogic)
    const { ratingForKey } = useValues(messageRatingsLogic)
    const { setRating } = useActions(messageRatingsLogic)
    const { user } = useValues(userLogic)
    const { isDev, preflight } = useValues(preflightLogic)
    const contextTraceId = useTraceId()

    // Use the context trace_id if available (for reloaded conversations), otherwise fall back to logic's traceId
    const traceId = contextTraceId || logicTraceId

    const rating = ratingForKey(traceId)
    const [feedback, setFeedback] = useState<string>('')
    const [feedbackInputStatus, setFeedbackInputStatus] = useState<'hidden' | 'pending' | 'submitted'>('hidden')

    function submitRating(newRating: 'good' | 'bad'): void {
        if (rating || !traceId) {
            return // Already rated
        }
        setRating({ key: traceId, rating: newRating })
        posthog.captureTraceMetric(traceId, 'quality', newRating)
        if (newRating === 'bad') {
            setFeedbackInputStatus('pending')
        }
    }

    function submitFeedback(): void {
        if (!feedback || !traceId) {
            return // Input is empty
        }
        posthog.captureTraceFeedback(traceId, feedback)
        setFeedbackInputStatus('submitted')
    }

    const traceUrl =
        (user?.is_staff || isDev) && traceId
            ? `${preflight?.region === Region.EU ? 'https://us.posthog.com/project/2' : ''}${urls.aiObservabilityTrace(traceId)}`
            : null

    return {
        traceId,
        rating,
        submitRating,
        feedback,
        setFeedback,
        feedbackInputStatus,
        closeFeedback: () => setFeedbackInputStatus('hidden'),
        submitFeedback,
        traceUrl,
    }
}
