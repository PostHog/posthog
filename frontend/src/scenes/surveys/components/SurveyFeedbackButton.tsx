import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

/**
 * This button does not have any logic attached to it, as that's added using a survey from PostHog.
 * On prod, the survey is https://us.posthog.com/project/2/surveys/0196afd4-6617-0000-0bbf-8b0db5b160f9
 */
export function SurveyFeedbackButton(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const newSceneLayout = featureFlags[FEATURE_FLAGS.NEW_SCENE_LAYOUT]

    return (
        <LemonButton
            size="small"
            type={!newSceneLayout ? 'secondary' : undefined}
            id="surveys-page-feedback-button"
            tooltip={newSceneLayout ? 'Have any questions or feedback?' : undefined}
        >
            {newSceneLayout ? 'Feedback' : 'Have any questions or feedback?'}
        </LemonButton>
    )
}
