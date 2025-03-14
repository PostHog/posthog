import { OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'

export function OnboardingErrorTrackingSourceMapsStep({ stepKey }: { stepKey: OnboardingStepKey }): JSX.Element {
    return (
        <OnboardingStep
            title="Link source maps"
            stepKey={stepKey}
            // continueOverride={<></>}
            // showSkip={currentStep == 1}
        >
            Hello
        </OnboardingStep>
    )
}
