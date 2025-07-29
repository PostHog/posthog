import { BindLogic, useActions, useValues } from 'kea'
import { NewSourcesWizard } from 'scenes/data-warehouse/new/NewSourceWizard'
import { sourceWizardLogic } from 'scenes/data-warehouse/new/sourceWizardLogic'

import { onboardingLogic } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { OnboardingStepKey } from '~/types'
import { availableSourcesDataLogic } from 'scenes/data-warehouse/new/availableSourcesDataLogic'
import { LemonSkeleton } from '@posthog/lemon-ui'

export function OnboardingDataWarehouseSourcesStep({
    stepKey = OnboardingStepKey.INSTALL,
}: {
    stepKey?: OnboardingStepKey
}): JSX.Element {
    const { goToNextStep } = useActions(onboardingLogic)
    const { currentStep } = useValues(sourceWizardLogic)
    const { availableSources, availableSourcesLoading } = useValues(availableSourcesDataLogic)

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
            {availableSourcesLoading || availableSources === null ? (
                <LemonSkeleton />
            ) : (
                <BindLogic logic={sourceWizardLogic} props={{ availableSources }}>
                    <NewSourcesWizard disableConnectedSources onComplete={() => goToNextStep()} />
                </BindLogic>
            )}
        </OnboardingStep>
    )
}
