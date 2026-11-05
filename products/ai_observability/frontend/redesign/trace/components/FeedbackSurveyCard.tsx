import { LemonTag } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { TraceSurveyResponseApi, TraceSurveyResponseApiUnavailable } from '../../../generated/api.schemas'
import { FeedbackPlacement } from '../types'
import { FeedbackSurveyName } from './FeedbackSurveyName'
import { scrollIntoNearest } from './scrollIntoNearest'
import { ShortTimestamp } from './ShortTimestamp'
import { SurveyAnswerView } from './SurveyAnswerView'

const UNAVAILABLE_MESSAGES: Record<NonNullable<TraceSurveyResponseApiUnavailable>, string> = {
    survey_not_found: "This survey was deleted, so its answers can't be shown.",
    no_questions: 'This survey has no questions.',
}

export interface FeedbackSurveyCardProps {
    response: TraceSurveyResponseApi & FeedbackPlacement
    /** Brings the card into view when it mounts. */
    isScrollTarget: boolean
}

export function FeedbackSurveyCard({ response, isScrollTarget }: FeedbackSurveyCardProps): JSX.Element {
    return (
        <li
            ref={isScrollTarget ? scrollIntoNearest : undefined}
            className={cn('flex flex-col gap-2 px-3 py-2', response.focused && 'bg-accent-highlight-secondary')}
        >
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                <FeedbackSurveyName survey={response.survey} />
                {response.complete ? null : (
                    <LemonTag type="muted" size="small">
                        Partial response
                    </LemonTag>
                )}
                <span className="ml-auto text-secondary">
                    <ShortTimestamp time={response.timestamp} />
                </span>
            </div>
            {response.unavailable ? (
                <p className="m-0 text-sm text-secondary">{UNAVAILABLE_MESSAGES[response.unavailable]}</p>
            ) : (
                response.answers.map((answer, index) => <SurveyAnswerView key={index} answer={answer} />)
            )}
        </li>
    )
}
