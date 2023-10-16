import { LemonButton } from '@posthog/lemon-ui'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { OnboardingStepKey, onboardingLogic } from './onboardingLogic'
import { useActions, useValues } from 'kea'
import { IconArrowLeft, IconArrowRight } from 'lib/lemon-ui/icons'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

export const OnboardingStep = ({
    stepKey,
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
    const { hasNextStep, hasPreviousStep } = useValues(onboardingLogic)
    const { completeOnboarding, goToNextStep, goToPreviousStep } = useActions(onboardingLogic)
    if (!stepKey) {
        throw new Error('stepKey is required in any OnboardingStep')
    }

    return (
        <BridgePage
            view="onboarding-step"
            noLogo
            hedgehog={false}
            fixedWidth={false}
            header={
                <div className="mb-4">
                    <LemonButton
                        icon={<IconArrowLeft />}
                        onClick={() => (hasPreviousStep ? goToPreviousStep() : router.actions.push(urls.products()))}
                    >
                        Back
                    </LemonButton>
                </div>
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
                                !hasNextStep ? completeOnboarding() : goToNextStep()
                            }}
                            status="muted"
                        >
                            Skip {!hasNextStep ? 'and finish' : 'for now'}
                        </LemonButton>
                    )}
                    {continueOverride ? (
                        continueOverride
                    ) : (
                        <LemonButton
                            type="primary"
                            onClick={() => (!hasNextStep ? completeOnboarding() : goToNextStep())}
                            sideIcon={hasNextStep ? <IconArrowRight /> : null}
                        >
                            {!hasNextStep ? 'Finish' : 'Continue'}
                        </LemonButton>
                    )}
                </div>
            </div>
        </BridgePage>
    )
}
