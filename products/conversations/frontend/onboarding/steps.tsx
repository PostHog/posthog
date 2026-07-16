import { type ProductOnboardingProvider } from 'scenes/onboarding/legacy/types'
import { urls } from 'scenes/urls'

// Support has no product-specific onboarding screen worth showing: enabling the product and
// configuring channels both live in Support settings. `conversations_enabled` is flipped on
// onboarding completion in onboardingLogic (see ProductKey.CONVERSATIONS there), so the flow is
// just the shared trailing steps, then a redirect into the product.
export const conversationsOnboarding: ProductOnboardingProvider = {
    steps: () => [],
    completeRedirectUrl: () => urls.supportTickets(),
}
