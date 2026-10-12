import { useActions, useValues } from 'kea'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { OnboardingStepKey } from '~/types'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'
import { InlineSourceSetup } from 'products/data_warehouse/frontend/shared/components/InlineSourceSetup'

import { OnboardingStepComponentType, onboardingLogic } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'

export const OnboardingDataWarehouseSourcesStep: OnboardingStepComponentType = () => {
    const { goToNextStep } = useActions(onboardingLogic)
    const { reportOnboardingStepCompleted } = useActions(eventUsageLogic)
    const { availableSourcesLoading } = useValues(availableSourcesLogic)
    return (
        <OnboardingStep
            title="Connect your data for better insights"
            stepKey={OnboardingStepKey.LINK_DATA}
            showContinue={false}
            showSkip={!availableSourcesLoading}
            subtitle="Link sources like Stripe and Hubspot so you can query them alongside product data to find correlations."
        >
            <InlineSourceSetup
                onComplete={() => {
                    reportOnboardingStepCompleted(OnboardingStepKey.LINK_DATA)
                    goToNextStep()
                }}
                featured
                showWizard
                autoConfigureTables
                subtitle="You can always connect more sources later."
            />
        </OnboardingStep>
    )
}

OnboardingDataWarehouseSourcesStep.stepKey = OnboardingStepKey.LINK_DATA
