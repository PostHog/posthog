import { LemonBanner, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LinkToSurveyFormSection } from 'scenes/surveys/components/LinkToSurveyFormSection'
import { SurveyEditSection, surveyLogic } from 'scenes/surveys/surveyLogic'

export function SurveyResponsesCollection(): JSX.Element | null {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)

    return (
        <div className="flex flex-col gap-1">
            <LemonField.Pure
                inline
                label={<h3 className="mb-0">Enable partial responses</h3>}
                info="Requires at least version 1.240.0 or higher of posthog-js. Doesn't work with the mobile SDKs for now."
                htmlFor="enable-partial-responses"
            >
                <LemonSwitch
                    id="enable-partial-responses"
                    checked={!!survey.enable_partial_responses}
                    onChange={(newValue) => {
                        setSurveyValue('enable_partial_responses', newValue)
                    }}
                />
            </LemonField.Pure>
            {survey.appearance?.shuffleQuestions && survey.enable_partial_responses && (
                <LemonBanner type="info" hideIcon>
                    <h3 className="mb-0">Shuffle questions does not work with partial responses.</h3>
                    <p>
                        Shuffle questions is currently enabled for your survey. However, it will have no effect if
                        partial responses are enabled. Go to the{' '}
                        <LinkToSurveyFormSection section={SurveyEditSection.Customization} /> to disable it.
                    </p>
                    <p>
                        This is a temporary limitation that we'll fix in a future release. There's no action needed from
                        you, just know that the order of the questions won't be shuffled if partial responses are
                        enabled.
                    </p>
                </LemonBanner>
            )}
        </div>
    )
}
