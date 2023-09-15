import { LemonButton } from '@posthog/lemon-ui'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { onboardingLogic } from './onboardingLogic'
import { useActions, useValues } from 'kea'
import { IconArrowLeft, IconArrowRight } from 'lib/lemon-ui/icons'

export const OnboardingStep = ({
    title,
    subtitle,
    children,
    showSkip = false,
}: {
    title: string
    subtitle?: string
    children: React.ReactNode
    showSkip?: boolean
}): JSX.Element => {
    const { onboardingStep, totalOnboardingSteps } = useValues(onboardingLogic)
    const { setOnboardingStep, completeOnboarding } = useActions(onboardingLogic)
    return (
        <BridgePage
            view="onboarding-step"
            noLogo
            hedgehog={false}
            fixedWidth={false}
            header={
                onboardingStep > 1 && (
                    <div className="mb-4">
                        <LemonButton icon={<IconArrowLeft />} onClick={() => setOnboardingStep(onboardingStep - 1)}>
                            Back
                        </LemonButton>
                    </div>
                )
            }
        >
            <div className="max-w-md">
                <h1 className="font-bold">{title}</h1>
                <p>{subtitle}</p>
                {children}
                <div className="mt-8 flex justify-end gap-x-2">
                    {showSkip && (
                        <LemonButton
                            type="tertiary"
                            onClick={() =>
                                onboardingStep == totalOnboardingSteps
                                    ? completeOnboarding()
                                    : setOnboardingStep(onboardingStep + 1)
                            }
                            status="muted"
                        >
                            Skip for now
                        </LemonButton>
                    )}
                    <LemonButton
                        type="primary"
                        onClick={() =>
                            onboardingStep == totalOnboardingSteps
                                ? completeOnboarding()
                                : setOnboardingStep(onboardingStep + 1)
                        }
                        sideIcon={onboardingStep !== totalOnboardingSteps ? <IconArrowRight /> : null}
                    >
                        {onboardingStep == totalOnboardingSteps ? 'Finish' : 'Continue'}
                    </LemonButton>
                </div>
            </div>
        </BridgePage>
    )
}
