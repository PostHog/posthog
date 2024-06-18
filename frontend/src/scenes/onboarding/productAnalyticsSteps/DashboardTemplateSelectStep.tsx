import { LemonButton } from '@posthog/lemon-ui'
import { useActions } from 'kea'
import { DashboardTemplateChooser } from 'scenes/dashboard/DashboardTemplateChooser'

import { onboardingLogic, OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'

export const OnboardingDashboardTemplateSelectStep = ({
    stepKey = OnboardingStepKey.DASHBOARD_TEMPLATE,
}: {
    stepKey?: OnboardingStepKey
}): JSX.Element => {
    const { goToNextStep } = useActions(onboardingLogic)

    return (
        <OnboardingStep
            title="Start with a dashboard template"
            stepKey={stepKey}
            continueOverride={
                <LemonButton
                    type="secondary"
                    onClick={() => {
                        goToNextStep(2)
                    }}
                    data-attr="onboarding-skip-button"
                >
                    Skip for now
                </LemonButton>
            }
        >
            <p>
                Get useful insights from your events super fast with our dashboard templates. Select one to get started
                with based on your market and industry.
            </p>
            <DashboardTemplateChooser onItemClick={goToNextStep} />
        </OnboardingStep>
    )
}
