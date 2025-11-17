import { BindLogic, useActions, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { NewSourcesWizard } from 'scenes/data-warehouse/new/NewSourceWizard'
import { availableSourcesDataLogic } from 'scenes/data-warehouse/new/availableSourcesDataLogic'
import { sourceWizardLogic } from 'scenes/data-warehouse/new/sourceWizardLogic'

import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from '../OnboardingStep'
import { onboardingLogic } from '../onboardingLogic'

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
                    <NewSourcesWizard onComplete={() => goToNextStep()} />
                </BindLogic>
            )}
        </OnboardingStep>
    )
}
