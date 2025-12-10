import { useActions, useValues } from 'kea'

import { InlineSourceSetup } from 'scenes/data-warehouse/new/InlineSourceSetup'
import { availableSourcesDataLogic } from 'scenes/data-warehouse/new/availableSourcesDataLogic'

import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from '../OnboardingStep'
import { onboardingLogic } from '../onboardingLogic'

export function OnboardingDataWarehouseSourcesStep({
    stepKey = OnboardingStepKey.INSTALL,
}: {
    stepKey?: OnboardingStepKey
}): JSX.Element {
    const { goToNextStep } = useActions(onboardingLogic)
    const { availableSourcesLoading } = useValues(availableSourcesDataLogic)

    return (
        <OnboardingStep
            title="Connect your data"
            stepKey={stepKey}
            showContinue={false}
            showSkip={!availableSourcesLoading}
            subtitle="Link your important data from your CRM, payment processor, or database and query across them seamlessly."
        >
            <InlineSourceSetup
                onComplete={() => goToNextStep()}
                featured
                title="Connect a data source"
                subtitle="Choose a source to import data from."
            />
        </OnboardingStep>
    )
}
