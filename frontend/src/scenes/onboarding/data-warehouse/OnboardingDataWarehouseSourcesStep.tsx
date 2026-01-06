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
            title="Connect your data for better insights"
            stepKey={stepKey}
            showContinue={false}
            showSkip={!availableSourcesLoading}
            subtitle="Link sources like Stripe and Hubspot so you can query them alongside product data to find correlations."
        >
            <InlineSourceSetup
                onComplete={() => goToNextStep()}
                featured
                title="Choose from 20+ sources"
                subtitle="You can always connect more sources later."
            />
        </OnboardingStep>
    )
}
