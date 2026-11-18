import type { TraceUnansweredSurveyApi } from '../../../generated/api.schemas'
import { FeedbackSurveyName } from './FeedbackSurveyName'
import { ShortTimestamp } from './ShortTimestamp'

export interface UnansweredSurveyRowProps {
    item: TraceUnansweredSurveyApi
}

export function UnansweredSurveyRow({ item }: UnansweredSurveyRowProps): JSX.Element {
    return (
        <li className="flex flex-wrap items-center gap-x-2 gap-y-1 px-3 py-1.5 text-xs text-secondary">
            <FeedbackSurveyName survey={item.survey} />
            <span className="ml-auto flex items-center gap-1">
                <span>Shown</span>
                <ShortTimestamp time={item.timestamp} />
            </span>
        </li>
    )
}
