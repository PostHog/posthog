import { useActions, useValues } from 'kea'

import { GuidedWizardStepper } from 'lib/components/GuidedWizard/GuidedWizardStepper'

import { OnboardingFlowHost } from '../OnboardingFlowHost'
import { stepKeyToTitle } from '../onboardingFlowUtils'
import { onboardingLogic } from '../onboardingLogic'

/** One product's onboarding steps, rendered inside the welcome page instead of the onboarding scene. */
export function WelcomeProductSetup(): JSX.Element {
    const { flow, currentFlowStep } = useValues(onboardingLogic)
    const { setStepId } = useActions(onboardingLogic)

    return (
        <div className="flex flex-col gap-2">
            {flow.length > 1 && currentFlowStep && (
                <GuidedWizardStepper
                    steps={flow.map((step) => ({
                        step: step.id,
                        label: step.label ?? stepKeyToTitle(step.stepKey) ?? '',
                        dataAttr: 'onboarding-welcome-step',
                    }))}
                    currentStep={currentFlowStep.id}
                    onStepClick={setStepId}
                    className="flex-wrap"
                    aria-label="Setup steps"
                />
            )}
            <OnboardingFlowHost />
        </div>
    )
}
