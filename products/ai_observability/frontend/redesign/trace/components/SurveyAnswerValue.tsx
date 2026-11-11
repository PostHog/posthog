import { IconThumbsDown, IconThumbsUp } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { SurveyAnswer } from '../types'

export interface SurveyAnswerValueProps {
    answer: SurveyAnswer
}

export function SurveyAnswerValue({ answer }: SurveyAnswerValueProps): JSX.Element {
    switch (answer.kind) {
        case 'thumbs':
            return (
                <span className="flex items-center gap-1 text-sm">
                    {answer.up ? <IconThumbsUp /> : <IconThumbsDown />}
                    <span>{answer.up ? 'Thumbs up' : 'Thumbs down'}</span>
                </span>
            )
        case 'rating':
            return (
                <span className="flex flex-wrap items-baseline gap-x-2 text-sm">
                    <span className="font-semibold">
                        {answer.scale ? `${answer.value} / ${answer.scale}` : answer.value}
                    </span>
                    {answer.lowerLabel && answer.upperLabel ? (
                        <span className="text-xs text-secondary">{`${answer.lowerLabel} to ${answer.upperLabel}`}</span>
                    ) : null}
                </span>
            )
        case 'choice':
            return (
                <span className="flex flex-wrap gap-1">
                    {answer.choices.map((choice) => (
                        <LemonTag key={choice} weight="normal">
                            {choice}
                        </LemonTag>
                    ))}
                </span>
            )
        case 'text':
            return <p className="m-0 whitespace-pre-wrap break-words text-sm">{answer.text}</p>
    }
}
