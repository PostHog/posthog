import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'

import { SurveyQuestion } from '~/types'

export function ThumbsResponse({
    isPositive,
    question,
}: {
    isPositive: boolean
    question: SurveyQuestion
}): JSX.Element {
    return (
        <div className="flex items-center gap-3">
            <span
                className={`inline-flex items-center justify-center size-8 rounded-md ${
                    isPositive ? 'bg-[var(--brand-blue-light)]' : 'bg-warning-highlight'
                }`}
            >
                {isPositive ? (
                    <IconThumbsUp className="size-5 text-brand-blue" />
                ) : (
                    <IconThumbsDown className="size-5 text-warning" />
                )}
            </span>
            <div className="flex flex-col">
                {question.question && <span className="text-xs text-muted">{question.question}</span>}
                <span className={`text-sm font-medium ${isPositive ? 'text-brand-blue' : 'text-warning'}`}>
                    {isPositive ? 'Positive' : 'Negative'}
                </span>
            </div>
        </div>
    )
}
