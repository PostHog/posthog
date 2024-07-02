import { useActions } from 'kea'
import { NewSourcesWizard } from 'scenes/data-warehouse/new/NewSourceWizard'

import { onboardingLogic, OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'

export function Sources({
    stepKey = OnboardingStepKey.INSTALL,
}: {
    usersAction?: string
    subtitle?: string
    stepKey?: OnboardingStepKey
}): JSX.Element {
    const { goToNextStep } = useActions(onboardingLogic)

    return (
        <OnboardingStep title="Install" stepKey={stepKey} continueOverride={<></>}>
            <NewSourcesWizard onComplete={() => goToNextStep()} />
        </OnboardingStep>
    )
}
