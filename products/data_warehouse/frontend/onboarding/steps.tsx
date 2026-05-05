import { OnboardingDataWarehouseSourcesStep } from 'scenes/onboarding/data-warehouse/OnboardingDataWarehouseSourcesStep'
import { type ProductOnboardingProvider } from 'scenes/onboarding/types'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

// `completeRedirectUrl` intentionally omitted: data warehouse falls through to
// urls.default() — same behaviour as the original central switch.
export const dataWarehouseOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => [
        {
            id: `${OnboardingStepKey.LINK_DATA}:${ProductKey.DATA_WAREHOUSE}`,
            productKey: ProductKey.DATA_WAREHOUSE,
            stepKey: OnboardingStepKey.LINK_DATA,
            role: ctx.role,
            render: () => <OnboardingDataWarehouseSourcesStep />,
        },
    ],
}
