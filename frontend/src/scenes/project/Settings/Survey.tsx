import { LemonDivider, Link } from '@posthog/lemon-ui'
import { SurveySettings as BasicSurveySettings } from 'scenes/surveys/SurveySettings'
import { urls } from 'scenes/urls'

export function SurveySettings(): JSX.Element {
    return (
        <>
            <h2 id="surveys" className="subtitle">
                Surveys
            </h2>
            <p>
                Get qualitative and quantitative data on how your users are doing. Surveys are found in the{' '}
                <Link to={urls.surveys()}>surveys page</Link>.
            </p>

            <BasicSurveySettings />
            <LemonDivider className="my-6" />
        </>
    )
}
