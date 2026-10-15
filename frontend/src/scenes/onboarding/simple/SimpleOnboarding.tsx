import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { OnboardingFlowHost } from '../OnboardingFlowHost'
import { onboardingLogic } from '../onboardingLogic'
import { ProjectTokenSnippet } from '../shared/ProjectTokenSnippet'

export function SimpleOnboarding(): JSX.Element {
    const { isSkippingOnboarding } = useValues(onboardingLogic)
    const { skipSimpleOnboarding } = useActions(onboardingLogic)

    return (
        <div className="flex flex-col gap-6">
            <div className="flex flex-wrap items-end justify-between gap-4 pb-6 border-b border-primary">
                <div className="flex-1 min-w-60 max-w-md">
                    <ProjectTokenSnippet />
                </div>
                <LemonButton
                    type="tertiary"
                    size="small"
                    onClick={skipSimpleOnboarding}
                    loading={isSkippingOnboarding}
                    data-attr="simple-onboarding-skip"
                >
                    Skip setup and go to PostHog
                </LemonButton>
            </div>
            <OnboardingFlowHost />
        </div>
    )
}
