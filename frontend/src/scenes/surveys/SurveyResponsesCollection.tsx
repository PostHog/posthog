import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { SurveyPartialResponses } from '~/types'

export function SurveyResponsesCollection(): JSX.Element | null {
    const { survey } = useValues(surveyLogic)
    const { setSurveyValue } = useActions(surveyLogic)

    const { featureFlags } = useValues(enabledFeaturesLogic)

    if (!featureFlags[FEATURE_FLAGS.SURVEYS_PARTIAL_RESPONSES]) {
        return null
    }

    return (
        <LemonField.Pure
            label={<h3 className="mb-0">Do you want to store partial responses?</h3>}
            info="If you enable this, we'll store responses even if the user does not complete the survey."
        >
            <LemonRadio
                value={survey.store_partial_responses ? SurveyPartialResponses.Yes : SurveyPartialResponses.No}
                onChange={(newValue) => {
                    setSurveyValue('store_partial_responses', newValue === SurveyPartialResponses.Yes ? true : false)
                }}
                options={[
                    {
                        value: SurveyPartialResponses.Yes,
                        label: 'Yes',
                    },
                    {
                        value: SurveyPartialResponses.No,
                        label: 'No',
                    },
                ]}
            />
        </LemonField.Pure>
    )
}
