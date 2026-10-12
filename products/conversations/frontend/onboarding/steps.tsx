import { type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { urls } from 'scenes/urls'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { OnboardingSupportStep } from './OnboardingSupportStep'

// Enabling the product and configuring channels both live in Support settings, and
// `conversations_enabled` is flipped on onboarding completion in onboardingLogic (see
// ProductKey.CONVERSATIONS there). The setup step must stay unconditional: every shared
// trailing step can be absent, and an empty flow strands the user on an error banner.
export const conversationsOnboarding: ProductOnboardingProvider = {
    steps: (ctx) => [
        {
            id: `${OnboardingStepKey.PRODUCT_CONFIGURATION}:${ProductKey.CONVERSATIONS}`,
            productKey: ProductKey.CONVERSATIONS,
            stepKey: OnboardingStepKey.PRODUCT_CONFIGURATION,
            label: 'Set up',
            role: ctx.role,
            render: () => <OnboardingSupportStep />,
        },
    ],
    completeRedirectUrl: () => urls.supportTickets(),
}
