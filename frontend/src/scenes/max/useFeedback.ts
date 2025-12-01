import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { feedbackPromptLogic } from './feedbackPromptLogic'
import { maxThreadLogic } from './maxThreadLogic'

export interface UseFeedbackResult {
    isPromptVisible: boolean
    isDetailedFeedbackVisible: boolean
    isThankYouVisible: boolean
    traceId: string | null
}

export function useFeedback(conversationId: string | null): UseFeedbackResult {
    const { threadGrouped, streamingActive, traceId, retryCount, cancelCount } = useValues(maxThreadLogic)

    // Only use feedback logic when we have a valid conversationId
    const feedbackLogicProps = useMemo(() => (conversationId ? { conversationId } : null), [conversationId])
    const feedbackLogic = feedbackLogicProps
        ? feedbackPromptLogic(feedbackLogicProps)
        : feedbackPromptLogic.build({ conversationId: '' })

    const { isPromptVisible, isDetailedFeedbackVisible, isThankYouVisible } = useValues(feedbackLogic)
    const { checkShouldShowPrompt, implicitDismissPrompt, implicitDismissDetailedFeedback } = useActions(feedbackLogic)

    const prevMessageCountRef = useRef(threadGrouped.length)
    const prevStreamingActiveRef = useRef(streamingActive)

    useEffect(() => {
        if (!conversationId) {
            return
        }

        const humanMessageCount = threadGrouped.filter((m) => m.type === 'human').length
        const wasStreaming = prevStreamingActiveRef.current
        const prevCount = prevMessageCountRef.current

        // Trigger feedback check when streaming completes
        if (wasStreaming && !streamingActive && humanMessageCount > 0) {
            checkShouldShowPrompt(humanMessageCount, retryCount, cancelCount)
        }

        // If prompt is visible and user sends a new message (count increased), trigger implicit dismiss
        if (isPromptVisible && humanMessageCount > prevCount && streamingActive) {
            implicitDismissPrompt()
        }

        // If detailed feedback form is visible and user sends a new message, submit "bad" rating and dismiss
        if (isDetailedFeedbackVisible && humanMessageCount > prevCount && streamingActive) {
            implicitDismissDetailedFeedback()
        }

        prevMessageCountRef.current = humanMessageCount
        prevStreamingActiveRef.current = streamingActive
    }, [
        threadGrouped,
        streamingActive,
        checkShouldShowPrompt,
        isPromptVisible,
        isDetailedFeedbackVisible,
        implicitDismissPrompt,
        implicitDismissDetailedFeedback,
        conversationId,
        retryCount,
        cancelCount,
    ])

    return {
        isPromptVisible,
        isDetailedFeedbackVisible,
        isThankYouVisible,
        traceId,
    }
}
