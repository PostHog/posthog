import { LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

export function SurveyResponsesCollection(): JSX.Element | null {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)

    return (
        <LemonSwitch
            tooltip="If you enable this, we'll store responses even if the user does not complete the survey. Requires version X.XXX.X or higher of posthog-js."
            label={<h3 className="mb-0">Enable partial responses</h3>}
            checked={!!survey.enable_partial_responses}
            onChange={(newValue) => {
                setSurveyValue('enable_partial_responses', newValue)
            }}
            className="p-0 gap-8"
        />
    )
}
