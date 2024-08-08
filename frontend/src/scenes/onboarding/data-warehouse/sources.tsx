import { useActions, useValues } from 'kea'
import { NewSourcesWizard } from 'scenes/data-warehouse/new/NewSourceWizard'
import { sourceWizardLogic } from 'scenes/data-warehouse/new/sourceWizardLogic'

import { onboardingLogic, OnboardingStepKey } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'

export function DataWarehouseSources({
    stepKey = OnboardingStepKey.INSTALL,
}: {
    usersAction?: string
    subtitle?: string
    stepKey?: OnboardingStepKey
}): JSX.Element {
    const { goToNextStep } = useActions(onboardingLogic)
    const { currentStep } = useValues(sourceWizardLogic)

    return (
        <OnboardingStep
            title="Link data"
            stepKey={stepKey}
            continueOverride={<></>}
            showSkip={currentStep == 1}
            subtitle={
                currentStep == 1
                    ? `Link all your important data from your CRM, payment processor, 
                or database and query across them seamlessly.`
                    : undefined
            }
        >
            <NewSourcesWizard onComplete={() => goToNextStep()} />
        </OnboardingStep>
    )
}
