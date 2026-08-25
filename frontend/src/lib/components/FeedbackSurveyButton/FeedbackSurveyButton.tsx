import posthog, { DisplaySurveyType } from 'posthog-js'
import { useEffect, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

export interface FeedbackSurveyButtonProps {
    surveyId: string
    'data-attr'?: string
}

/**
 * Opens an in-app survey as a popover, waiting for the surveys extension before allowing a click.
 * The plain, iconless styling is the intended standard for in-app feedback buttons — new ones
 * should use this component rather than adding another variant.
 */
export function FeedbackSurveyButton({ surveyId, 'data-attr': dataAttr }: FeedbackSurveyButtonProps): JSX.Element {
    const [surveysLoaded, setSurveysLoaded] = useState(false)

    useEffect(
        () =>
            posthog.onSurveysLoaded((_, context) => {
                if (context) {
                    setSurveysLoaded(context.isLoaded)
                }
            }),
        []
    )

    return (
        <LemonButton
            size="small"
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
                })
            }
        >
            Feedback
        </LemonButton>
    )
}
