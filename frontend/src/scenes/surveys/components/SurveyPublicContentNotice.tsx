import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { SurveyType } from '~/types'

export function SurveyPublicContentNotice(): JSX.Element {
    const { survey } = useValues(surveyLogic)

    // Both survey kinds expose their content, but by different routes: in-app definitions ship to
    // every visitor through the SDK, while a hosted survey is a public page.
    const exposure =
        survey.type === SurveyType.ExternalSurvey
            ? 'This survey is a public page, so anyone with the link can read its name and questions. Keep private details out of them.'
            : "Everything you write here is sent to every visitor's browser so your app can show the survey. Anyone can read it, so keep private details out of names and question text."

    return (
        <LemonBanner type="info">{exposure} The survey description is the exception and stays in PostHog.</LemonBanner>
    )
}
