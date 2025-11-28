import './QuestionInput.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { feedbackPromptLogic } from '../feedbackPromptLogic'
import { FeedbackRating } from '../utils'

export interface FeedbackDisplayProps {
    isFloating?: boolean
    conversationId: string
}

export function FeedbackDisplay({ isFloating, conversationId }: FeedbackDisplayProps): JSX.Element | null {
    const { isPromptVisible } = useValues(feedbackPromptLogic({ conversationId }))
    const { submitRating } = useActions(feedbackPromptLogic({ conversationId }))

    // Global keyboard shortcuts - capture phase intercepts before input fields
    useEffect(() => {
        if (!isPromptVisible) {
            return
        }

        const keyToRating: Record<string, FeedbackRating> = {
            '1': 'okay',
            '2': 'good',
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
