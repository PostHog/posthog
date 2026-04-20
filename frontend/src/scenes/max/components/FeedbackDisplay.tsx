import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { feedbackPromptLogic } from '../feedbackPromptLogic'
import { FeedbackRating } from '../utils'

export interface FeedbackDisplayProps {
    conversationId: string
}

export function FeedbackDisplay({ conversationId }: FeedbackDisplayProps): JSX.Element | null {
    const { isPromptVisible } = useValues(feedbackPromptLogic({ conversationId }))
    const { submitRating } = useActions(feedbackPromptLogic({ conversationId }))

    // Global keyboard shortcuts - capture phase intercepts before input fields
    useEffect(() => {
        if (!isPromptVisible) {
            return
        }

        const keyToRating: Record<string, FeedbackRating> = {
            '1': 'good',
            '2': 'okay',
            '3': 'bad',
            x: 'dismissed',
        }

        const handleGlobalKeyDown = (e: KeyboardEvent): void => {
            const rating = keyToRating[e.key]
            if (rating) {
                e.preventDefault()
                e.stopPropagation()
                submitRating(rating)
            }
        }

        window.addEventListener('keydown', handleGlobalKeyDown, true)
        return () => window.removeEventListener('keydown', handleGlobalKeyDown, true)
    }, [isPromptVisible, submitRating])

    return (
        <div className="flex items-center gap-1">
            <LemonButton size="xsmall" type="secondary" onClick={() => submitRating('good')}>
                Good <span className="text-muted ml-0.5">1</span>
            </LemonButton>
            <LemonButton size="xsmall" type="secondary" onClick={() => submitRating('okay')}>
                Okay <span className="text-muted ml-0.5">2</span>
            </LemonButton>
            <LemonButton size="xsmall" type="secondary" onClick={() => submitRating('bad')}>
                Bad <span className="text-muted ml-0.5">3</span>
            </LemonButton>
            <LemonButton size="xsmall" type="secondary" onClick={() => submitRating('dismissed')}>
                Dismiss <span className="text-muted ml-0.5">x</span>
            </LemonButton>
        </div>
    )
}
