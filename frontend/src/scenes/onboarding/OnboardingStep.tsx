import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { IconArrowLeft, IconArrowRight } from 'lib/lemon-ui/icons'
import { urls } from 'scenes/urls'

import { onboardingLogic, OnboardingStepKey } from './onboardingLogic'

export const OnboardingStep = ({
    stepKey,
    title,
    subtitle,
    children,
    showSkip = false,
    onSkip,
    continueOverride,
    backActionOverride,
}: {
    stepKey: OnboardingStepKey
    title: string
    subtitle?: string
    children: React.ReactNode
    showSkip?: boolean
    onSkip?: () => void
    continueOverride?: JSX.Element
    backActionOverride?: () => void
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
                        onClick={() =>
                            backActionOverride
                                ? backActionOverride()
                                : hasPreviousStep
                                ? goToPreviousStep()
                                : router.actions.push(urls.products())
                        }
                    >
                        Back
                    </LemonButton>
                </div>
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
