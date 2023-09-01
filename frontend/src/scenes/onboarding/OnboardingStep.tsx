import { LemonButton } from '@posthog/lemon-ui'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { onboardingLogic } from './onboardingLogic'
import { useActions, useValues } from 'kea'

export const OnboardingStep = ({
    title,
    subtitle,
    children,
}: {
    title: string
    subtitle?: string
    children: React.ReactNode
}): JSX.Element => {
    const { onboardingStep, totalOnboardingSteps } = useValues(onboardingLogic)
    const { incrementOnboardingStep, completeOnboarding } = useActions(onboardingLogic)
    return (
        <BridgePage view="onboarding-step" noLogo hedgehog={false} fixedWidth={false}>
            <div className="max-w-md">
                <h1>{title}</h1>
                <p>{subtitle}</p>
                {children}
                <LemonButton
                    type="primary"
                    onClick={() =>
                        onboardingStep == totalOnboardingSteps ? completeOnboarding() : incrementOnboardingStep()
                    }
                >
                    {onboardingStep == totalOnboardingSteps ? 'Finish' : 'Continue'}
                </LemonButton>
            </div>
        </BridgePage>
    )
}
