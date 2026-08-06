import { LemonBanner } from '@posthog/lemon-ui'

export function SurveyPublicContentNotice(): JSX.Element {
    return (
        <LemonBanner type="info" dismissKey="survey-public-content-notice">
            Everything you write here is sent to every visitor's browser so your app can show the survey. Anyone can
            read it, so keep private details out of names and question text. The survey description is the exception and
            stays in PostHog.
        </LemonBanner>
    )
}
