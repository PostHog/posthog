import posthog, { DisplaySurveyType, type Properties } from 'posthog-js'
import { useEffect, useState } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

import { QuillFeedbackSurveyButton } from './QuillFeedbackSurveyButton'

export interface FeedbackSurveyButtonProps {
    surveyId: string
    properties?: Properties
    'data-attr'?: string
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
}: FeedbackSurveyButtonProps): JSX.Element {
    const [surveysLoaded, setSurveysLoaded] = useState(false)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    useEffect(
        () =>
            posthog.onSurveysLoaded((_, context) => {
                if (context) {
                    setSurveysLoaded(context.isLoaded)
                }
            }),
        []
    )

    if (todayRailNav) {
        return (
            <QuillFeedbackSurveyButton
                surveyId={surveyId}
                properties={properties}
                data-attr={dataAttr}
                surveysLoaded={surveysLoaded}
            />
        )
    }

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
                    properties,
                })
            }
        >
            Feedback
        </LemonButton>
    )
}
