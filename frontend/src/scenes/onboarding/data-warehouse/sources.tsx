import { NewSourceWizard } from 'scenes/data-warehouse/new/NewSourceWizard'

import { OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'

export function Sources({
    stepKey = OnboardingStepKey.INSTALL,
}: {
    usersAction?: string
    subtitle?: string
    stepKey?: OnboardingStepKey
}): JSX.Element {
    return (
        <OnboardingStep title="Install" stepKey={stepKey} continueOverride={<></>}>
            <NewSourceWizard />
        </OnboardingStep>
    )
}
