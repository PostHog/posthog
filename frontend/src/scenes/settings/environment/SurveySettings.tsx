import { Link } from '@posthog/lemon-ui'

import { SurveySettings as BasicSurveySettings } from 'scenes/surveys/SurveySettings'
import { urls } from 'scenes/urls'

export function SurveySettings(): JSX.Element {
    return (
        <>
            <p>
                Get qualitative and quantitative data on how your users are doing. Surveys are found in the{' '}
                <Link to={urls.surveys()}>surveys page</Link>.
            </p>

            <BasicSurveySettings />
        </>
    )
}
