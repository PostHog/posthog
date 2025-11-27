import './QuestionInput.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useCallback, useEffect } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { FeedbackRating, FeedbackTriggerType } from '../FeedbackPrompt'
import { feedbackPromptLogic } from '../feedbackPromptLogic'
import { maxThreadLogic } from '../maxThreadLogic'

export interface FeedbackDisplayProps {
    isFloating?: boolean
    conversationId: string
}

function captureMaxFeedback(
    traceId: string | null,
    rating: FeedbackRating,
    triggerType: FeedbackTriggerType,
    conversationId: string
): void {
    posthog.capture('posthog_ai_feedback_submitted', {
        $ai_conversation_id: conversationId,
        $ai_session_id: conversationId,
        $ai_trace_id: traceId,
        $ai_feedback_rating: rating,
        $ai_feedback_trigger_type: triggerType,
    })
}

export function FeedbackDisplay({ isFloating, conversationId }: FeedbackDisplayProps): JSX.Element | null {
    const { isPromptVisible, currentTriggerType, messageInterval } = useValues(feedbackPromptLogic({ conversationId }))
    const { hidePrompt, showDetailedFeedback, recordFeedbackShown, setLastTriggeredIntervalIndex } = useActions(
        feedbackPromptLogic({ conversationId })
    )
    const { traceId, threadGrouped } = useValues(maxThreadLogic)
    const { resetRetryCount, resetCancelCount } = useActions(maxThreadLogic)

    const submitRating = useCallback(
        (rating: FeedbackRating): void => {
            // For "bad" rating, show the detailed feedback form in the thread
            if (rating === 'bad') {
                showDetailedFeedback()
                return
            }

            captureMaxFeedback(traceId, rating, currentTriggerType, conversationId)
            recordFeedbackShown()
            resetRetryCount()
            resetCancelCount()
            // Set the interval index to current level so we don't re-trigger at the same message count
            const humanMessageCount = threadGrouped.filter((m: { type: string }) => m.type === 'human').length
            const currentIntervalIndex = Math.floor(humanMessageCount / messageInterval)
            setLastTriggeredIntervalIndex(currentIntervalIndex)
            hidePrompt()
        },
        [
            traceId,
            currentTriggerType,
            conversationId,
            recordFeedbackShown,
            hidePrompt,
            showDetailedFeedback,
            resetRetryCount,
            resetCancelCount,
            threadGrouped,
            messageInterval,
            setLastTriggeredIntervalIndex,
        ]
    )

    // Global keyboard shortcuts - capture phase intercepts before input fields
    useEffect(() => {
        if (!isPromptVisible) {
            return
        }

        const handleGlobalKeyDown = (e: KeyboardEvent): void => {
            switch (e.key) {
                case '1':
                    e.preventDefault()
                    e.stopPropagation()
                    submitRating('okay')
                    break
                case '2':
                    e.preventDefault()
                    e.stopPropagation()
                    submitRating('good')
                    break
                case '3':
                    e.preventDefault()
                    e.stopPropagation()
                    submitRating('bad')
                    break
                case 'x':
                    e.preventDefault()
                    e.stopPropagation()
                    submitRating('dismissed')
                    break
            }
        }

        window.addEventListener('keydown', handleGlobalKeyDown, true)
        return () => window.removeEventListener('keydown', handleGlobalKeyDown, true)
    }, [isPromptVisible, submitRating])

    if (!isPromptVisible) {
        return null
    }

    return (
        <div
            className={clsx(
                'flex items-center w-full cursor-default',
                !isFloating
                    ? 'px-1.5 pt-2 pb-1 -m-1 border-x border-b rounded-b backdrop-blur-sm bg-[var(--glass-bg-3000)]'
                    : 'px-2 pb-1 pt-0.5'
            )}
        >
            <div className={clsx('flex items-center gap-1', !isFloating && 'w-[calc(100%-1rem)]')}>
                <LemonButton size="xsmall" type="secondary" onClick={() => submitRating('okay')}>
                    Okay <span className="text-muted ml-0.5">1</span>
                </LemonButton>
                <LemonButton size="xsmall" type="secondary" onClick={() => submitRating('good')}>
                    Good <span className="text-muted ml-0.5">2</span>
                </LemonButton>
                <LemonButton size="xsmall" type="secondary" onClick={() => submitRating('bad')}>
                    Bad <span className="text-muted ml-0.5">3</span>
                </LemonButton>
                <LemonButton size="xsmall" type="secondary" onClick={() => submitRating('dismissed')}>
                    Dismiss <span className="text-muted ml-0.5">x</span>
                </LemonButton>
            </div>
        </div>
    )
}
