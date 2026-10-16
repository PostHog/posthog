import { availableOnboardingProducts, toSentenceCase } from 'scenes/onboarding/shared/utils'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { type OnboardingStepDescriptor } from '../types'
import { WelcomeProductReadyStep } from './WelcomeProductReadyStep'

/**
 * The welcome page's flow for one product: its own steps only, since plans and invites already had
 * their turn in the onboarding that led there. A product with no steps of its own still gets one,
 * because completing the flow is what turns the product on.
 */
export function buildWelcomeEmbeddedFlow(
    productSteps: OnboardingStepDescriptor[],
    primary: ProductKey
): OnboardingStepDescriptor[] {
    if (productSteps.length > 0) {
        return productSteps
    }
    const productName = toSentenceCase(
        availableOnboardingProducts[primary as keyof typeof availableOnboardingProducts]?.name ?? ''
    )
    return [
        {
            id: `${OnboardingStepKey.PRODUCT_CONFIGURATION}:${primary}`,
            productKey: primary,
            stepKey: OnboardingStepKey.PRODUCT_CONFIGURATION,
            label: 'Turn on',
            role: 'primary',
            render: () => <WelcomeProductReadyStep productName={productName} />,
        },
    ]
}
