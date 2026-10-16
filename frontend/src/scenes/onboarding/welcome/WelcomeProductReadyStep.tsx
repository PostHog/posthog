import { OnboardingStepKey } from '~/types'

import { OnboardingStep } from '../OnboardingStep'

/** The welcome page's only step for a product that has no setup steps of its own. */
export function WelcomeProductReadyStep({ productName }: { productName: string }): JSX.Element {
    return (
        <OnboardingStep
            stepKey={OnboardingStepKey.PRODUCT_CONFIGURATION}
            title={`Turn on ${productName}`}
            continueText={`Turn on ${productName}`}
        >
            <p>{productName} needs no setup before you start. Turn it on to open it.</p>
        </OnboardingStep>
    )
}
