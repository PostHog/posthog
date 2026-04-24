import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { OnboardingStepKey } from '~/types'

import { availableSourcesLogic } from 'products/data_warehouse/frontend/scenes/NewSourceScene/availableSourcesLogic'
import { InlineSourceSetup } from 'products/data_warehouse/frontend/shared/components/InlineSourceSetup'

import { OnboardingStepComponentType, onboardingLogic } from '../onboardingLogic'
import { OnboardingStep } from '../OnboardingStep'
import { DataWarehouseQueryVariant } from './DataWarehouseQueryVariant'
import { DataWarehouseValuePropVariant } from './DataWarehouseValuePropVariant'

export const OnboardingDataWarehouseSourcesStep: OnboardingStepComponentType = () => {
    const { goToNextStep } = useActions(onboardingLogic)
    const { reportOnboardingStepCompleted } = useActions(eventUsageLogic)
    const { availableSourcesLoading } = useValues(availableSourcesLogic)
    const isTableVariant = useFeatureFlag('ONBOARDING_DATA_WAREHOUSE_VALUE_PROP', 'table')
    const isQueryVariant = useFeatureFlag('ONBOARDING_DATA_WAREHOUSE_VALUE_PROP', 'query')

    if (isTableVariant) {
        return <DataWarehouseValuePropVariant />
    }

    if (isQueryVariant) {
        return <DataWarehouseQueryVariant />
    }

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
                title="Choose from 20+ sources"
                subtitle="You can always connect more sources later."
            />
        </OnboardingStep>
    )
}

OnboardingDataWarehouseSourcesStep.stepKey = OnboardingStepKey.LINK_DATA
