import { Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import type { TraceSurveyApi } from '../../../generated/api.schemas'

export interface FeedbackSurveyNameProps {
    survey: TraceSurveyApi
}

export function FeedbackSurveyName({ survey }: FeedbackSurveyNameProps): JSX.Element {
    if (survey.name === null) {
        return <span className="font-semibold text-secondary">Deleted survey</span>
    }
    return (
        <Link to={urls.survey(survey.id)} className="font-semibold" data-attr="trace-view-feedback-survey-link">
            {survey.name}
        </Link>
    )
}
