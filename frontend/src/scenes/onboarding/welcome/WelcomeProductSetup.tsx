import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { OnboardingFlowHost } from '../OnboardingFlowHost'
import { stepKeyToTitle } from '../onboardingFlowUtils'
import { onboardingLogic } from '../onboardingLogic'

/** One product's onboarding steps, rendered inside the welcome page instead of the onboarding scene. */
export function WelcomeProductSetup(): JSX.Element {
    const { flow, currentFlowStep } = useValues(onboardingLogic)
    const { setStepId } = useActions(onboardingLogic)

    return (
        <div className="flex flex-col gap-2">
            {flow.length > 1 && (
                <div className="flex flex-wrap gap-1" role="tablist" aria-label="Setup steps">
                    {flow.map((step, index) => (
                        <LemonButton
                            key={step.id}
                            size="small"
                            role="tab"
                            aria-selected={step.id === currentFlowStep?.id}
                            active={step.id === currentFlowStep?.id}
                            onClick={() => setStepId(step.id)}
                            data-attr="onboarding-welcome-step"
                        >
                            {`${index + 1}. ${step.label ?? stepKeyToTitle(step.stepKey)}`}
                        </LemonButton>
                    ))}
                </div>
            )}
            <OnboardingFlowHost />
        </div>
    )
}
