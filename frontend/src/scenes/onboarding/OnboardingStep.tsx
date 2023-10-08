import { LemonButton } from '@posthog/lemon-ui'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { OnboardingStepKey, onboardingLogic } from './onboardingLogic'
import { useActions, useValues } from 'kea'
import { IconArrowLeft, IconArrowRight } from 'lib/lemon-ui/icons'

export const OnboardingStep = ({
    stepKey, // eslint-disable-line @typescript-eslint/no-unused-vars
    title,
    subtitle,
    children,
    showSkip = false,
    onSkip,
    continueOverride,
}: {
    stepKey: OnboardingStepKey
    title: string
    subtitle?: string
    children: React.ReactNode
    showSkip?: boolean
    onSkip?: () => void
    continueOverride?: JSX.Element
}): JSX.Element => {
    const { currentOnboardingStepNumber, totalOnboardingSteps } = useValues(onboardingLogic)
    const { setCurrentOnboardingStepNumber, completeOnboarding } = useActions(onboardingLogic)
    const isLastStep = currentOnboardingStepNumber == totalOnboardingSteps
    return (
        <BridgePage
            view="onboarding-step"
            noLogo
            hedgehog={false}
            fixedWidth={false}
            header={
                currentOnboardingStepNumber > 1 && (
                    <div className="mb-4">
                        <LemonButton
                            icon={<IconArrowLeft />}
                            onClick={() => setCurrentOnboardingStepNumber(currentOnboardingStepNumber - 1)}
                        >
                            Back
                        </LemonButton>
                    </div>
                )
            }
        >
            <div className="w-md">
                <h1 className="font-bold">{title}</h1>
                <p>{subtitle}</p>
                {children}
                <div className="mt-8 flex justify-end gap-x-2">
                    {showSkip && (
                        <LemonButton
                            type="tertiary"
                            onClick={() => {
                                onSkip && onSkip()
                                isLastStep
                                    ? completeOnboarding()
                                    : setCurrentOnboardingStepNumber(currentOnboardingStepNumber + 1)
                            }}
                            status="muted"
                        >
                            Skip {isLastStep ? 'and finish' : 'for now'}
                        </LemonButton>
                    )}
                    {continueOverride ? (
                        continueOverride
                    ) : (
                        <LemonButton
                            type="primary"
                            onClick={() =>
                                currentOnboardingStepNumber == totalOnboardingSteps
                                    ? completeOnboarding()
                                    : setCurrentOnboardingStepNumber(currentOnboardingStepNumber + 1)
                            }
                            sideIcon={currentOnboardingStepNumber !== totalOnboardingSteps ? <IconArrowRight /> : null}
                        >
                            {currentOnboardingStepNumber == totalOnboardingSteps ? 'Finish' : 'Continue'}
                        </LemonButton>
                    )}
                </div>
            </div>
        </BridgePage>
    )
}
