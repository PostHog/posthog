import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
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
                info="Storing the response for any question requires at least version 1.240.0 or higher of posthog-js. Doesn't work with the mobile SDKs for now"
                label={<h3 className="mb-0">Response collection</h3>}
            >
                <LemonRadio
                    value={survey.enable_partial_responses ? 'true' : 'false'}
                    onChange={(newValue) => {
                        setSurveyValue('enable_partial_responses', newValue === 'true')
                    }}
                    options={[
                        {
                            value: 'true',
                            label: 'Any question: when at least one question is answered, the response is stored',
                        },
                        {
                            value: 'false',
                            label: 'Complete survey: the response is stored when all questions are answered',
                        },
                    ]}
                />
            </LemonField.Pure>
            <PartialResponsesShuffleQuestionsBanner />
        </div>
    )
}
