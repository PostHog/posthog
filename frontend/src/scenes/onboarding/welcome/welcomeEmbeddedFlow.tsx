import { availableOnboardingProducts, toSentenceCase } from 'scenes/onboarding/shared/utils'

import { ProductKey } from '~/queries/schema/schema-general'
import { OnboardingStepKey } from '~/types'

import { buildWizardInstallStep } from '../simple/simpleOnboardingFlow'
import { type OnboardingStepDescriptor } from '../types'
import { WelcomeProductReadyStep } from './WelcomeProductReadyStep'

/**
 * The welcome page's flow for one product: its own steps only, since plans and invites already had
 * their turn in the onboarding that led there. Every flow opens on an install step, so a product
 * without one gets the shared Wizard install first. A product with no steps of its own still gets
 * a closing step, because completing the flow is what turns the product on.
 */
export function buildWelcomeEmbeddedFlow(
    productSteps: OnboardingStepDescriptor[],
    primary: ProductKey
): OnboardingStepDescriptor[] {
    const installSteps = productSteps.some((step) => step.stepKey === OnboardingStepKey.INSTALL)
        ? []
        : [buildWizardInstallStep(primary)]
    if (productSteps.length > 0) {
        return [...installSteps, ...productSteps]
    }
    const productName = toSentenceCase(
        availableOnboardingProducts[primary as keyof typeof availableOnboardingProducts]?.name ?? ''
    )
    return [
        ...installSteps,
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
