import { ShopifyInstallation } from '@posthog/shared-onboarding/product-analytics/shopify'

import { OnboardingDocsContentWrapper } from 'scenes/onboarding/OnboardingDocsContentWrapper'

export function ProductAnalyticsShopifyInstructions(): JSX.Element {
    return (
        <OnboardingDocsContentWrapper>
            <ShopifyInstallation />
        </OnboardingDocsContentWrapper>
    )
}
