import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'
import { Callout, CalloutIcon, ItemContent, ItemDescription } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { surveyLogic } from 'scenes/surveys/surveyLogic'

import { SurveyType } from '~/types'

export function SurveyPublicContentNotice(): JSX.Element {
    const { survey } = useValues(surveyLogic)
    const quill = useFeatureFlag('LEMON_UI_TO_QUILL')

    // Both survey kinds expose their content, but by different routes: in-app definitions ship to
    // every visitor through the SDK, while a hosted survey is a public page.
    const exposure =
        survey.type === SurveyType.ExternalSurvey
            ? 'This survey is a public page, so anyone with the link can read its name and questions. Keep private details out of them.'
            : "Everything you write here is sent to every visitor's browser so your app can show the survey. Anyone can read it, so keep private details out of names and question text."

    const body = <>{exposure} The survey description is the exception and stays in PostHog.</>

    if (quill) {
        return (
            <Callout tone="info">
                <CalloutIcon />
                <ItemContent>
                    <ItemDescription>{body}</ItemDescription>
                </ItemContent>
            </Callout>
        )
    }

    return <LemonBanner type="info">{body}</LemonBanner>
}
