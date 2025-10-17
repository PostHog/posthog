import { useValues } from 'kea'

import { AuthorizedUrlList } from 'lib/components/AuthorizedUrlList/AuthorizedUrlList'
import { AuthorizedUrlListType, authorizedUrlListLogic } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'

import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from '../OnboardingStep'

export function OnboardingWebAnalyticsAuthorizedDomainsStep({
    stepKey = OnboardingStepKey.AUTHORIZED_DOMAINS,
}: {
    stepKey?: OnboardingStepKey
}): JSX.Element {
    const { authorizedUrls } = useValues(
        authorizedUrlListLogic({
            actionId: null,
            experimentId: null,
            type: AuthorizedUrlListType.WEB_ANALYTICS,
            allowWildCards: false,
        })
    )

    return (
        <OnboardingStep
            title="Authorized Domains"
            stepKey={stepKey}
            showSkip
            continueDisabledReason={authorizedUrls.length === 0 ? 'Add at least one authorized domain' : undefined}
        >
            <p>
                These are the domains we'll use as breakdown when looking at <b>Web Analytics</b>. Make sure you add all
                the domains you'll install PostHog at. These are also the URLs where our toolbar will be enabled.
            </p>
            <p>
                <b>Wildcards are not allowed</b> (example: <code>https://*.posthog.com</code>). The domain needs to be
                something concrete that can be launched (example: <code>https://app.posthog.com</code>).
            </p>

            <AuthorizedUrlList
                type={AuthorizedUrlListType.WEB_ANALYTICS}
                allowWildCards={false}
                displaySuggestions={false}
            />
        </OnboardingStep>
    )
}
