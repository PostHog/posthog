import { LemonBanner, LemonSwitch, LemonTag } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

export function PartialResponsesShuffleQuestionsBanner(): JSX.Element | null {
    const { survey } = useValues(surveyLogic)

    if (!survey.enable_partial_responses || !survey.appearance?.shuffleQuestions) {
        return null
    }

    return (
        <LemonBanner type="warning" hideIcon>
            <h3 className="mb-0">Shuffle questions does not work with partial responses.</h3>
            <p>
                Shuffle questions is currently enabled for your survey. But it is not supported with partial responses.
                Once the survey is saved, we'll disable shuffle questions for you. If you need to shuffle questions,
                please disable partial responses.
            </p>
        </LemonBanner>
    )
}

export function SurveyResponsesCollection(): JSX.Element | null {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)

    return (
        <div className="flex flex-col gap-1">
            <LemonField.Pure
                inline
                label={
                    <h3 className="mb-0 flex items-center gap-1">
                        <LemonTag type="warning">BETA</LemonTag>
                        Enable partial responses
                    </h3>
                }
                info="Requires at least version 1.240.0 or higher of posthog-js. Doesn't work with the mobile SDKs for now. If you face any issues when using partial responses, please report it to us."
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
            <PartialResponsesShuffleQuestionsBanner />
        </div>
    )
}
