import posthog, { DisplaySurveyType } from 'posthog-js'

import { Button } from '@posthog/quill'

import type { FeedbackSurveyButtonProps } from './FeedbackSurveyButton'

export function QuillFeedbackSurveyButton({
    surveyId,
    properties,
    'data-attr': dataAttr,
    surveysLoaded,
}: FeedbackSurveyButtonProps & { surveysLoaded: boolean }): JSX.Element {
    return (
        <Button
            data-attr={dataAttr}
            tooltip="Have any questions or feedback?"
            disabledReason={surveysLoaded ? undefined : 'Feedback is unavailable right now'}
            onClick={() =>
                // A deliberate click should always bring up the survey, so bypass the
                // popover's URL/cohort/already-dismissed targeting.
                posthog.displaySurvey(surveyId, {
                    displayType: DisplaySurveyType.Popover,
                    ignoreConditions: true,
                    ignoreDelay: true,
                    properties,
                })
            }
        >
            Feedback
        </Button>
    )
}
