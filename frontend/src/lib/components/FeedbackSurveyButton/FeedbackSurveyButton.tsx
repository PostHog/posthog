import posthog, { DisplaySurveyType, type Properties } from 'posthog-js'
import { useEffect, useState } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'

export interface FeedbackSurveyButtonProps {
    surveyId: string
    properties?: Properties
    'data-attr'?: string
    /** Button copy. Defaults to "Feedback". */
    label?: string
}

/**
 * Opens an in-app survey as a popover, waiting for the surveys extension before allowing a click.
 * The plain, iconless styling is the intended standard for in-app feedback buttons — new ones
 * should use this component rather than adding another variant.
 */
export function FeedbackSurveyButton({
    surveyId,
    properties,
    'data-attr': dataAttr,
    label = 'Feedback',
}: FeedbackSurveyButtonProps): JSX.Element {
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
            // Without this, LemonButton copies the string tooltip into aria-label, so the
            // accessible name would be the tooltip instead of the visible label.
            aria-label={label}
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
            {label}
        </LemonButton>
    )
}
