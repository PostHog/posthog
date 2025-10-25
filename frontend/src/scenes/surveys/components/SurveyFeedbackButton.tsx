import { LemonButton } from '@posthog/lemon-ui'

/**
 * This button does not have any logic attached to it, as that's added using a survey from PostHog.
 * On prod, the survey is https://us.posthog.com/project/2/surveys/0196afd4-6617-0000-0bbf-8b0db5b160f9
 */
export function SurveyFeedbackButton(): JSX.Element {
    return (
        <LemonButton size="small" id="surveys-page-feedback-button" tooltip="Have any questions or feedback?">
            Feedback
        </LemonButton>
    )
}
