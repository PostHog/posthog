import { OnboardingDataWarehouseSourcesStep } from 'scenes/onboarding/legacy/data-warehouse/OnboardingDataWarehouseSourcesStep'
import { type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

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
    // Land freshly-onboarded users on the sources list — where they can connect or manage a
    // source — instead of falling through to urls.default() (the home page), which drops the
    // data-warehouse intent on the floor. Every other product redirects to its own surface.
    completeRedirectUrl: () => urls.sources(),
}
