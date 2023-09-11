import { LemonButton } from '@posthog/lemon-ui'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { onboardingLogic } from './onboardingLogic'
import { useActions, useValues } from 'kea'
import { IconArrowLeft, IconArrowRight } from 'lib/lemon-ui/icons'

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
    const { incrementOnboardingStep, decrementOnboardingStep, completeOnboarding } = useActions(onboardingLogic)
    return (
        <BridgePage
            view="onboarding-step"
            noLogo
            hedgehog={false}
            fixedWidth={false}
            header={
                onboardingStep > 1 && (
                    <div className="mb-4">
                        <LemonButton icon={<IconArrowLeft />} onClick={decrementOnboardingStep}>
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
                    <LemonButton
                        type="primary"
                        onClick={() =>
                            onboardingStep == totalOnboardingSteps ? completeOnboarding() : incrementOnboardingStep()
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
