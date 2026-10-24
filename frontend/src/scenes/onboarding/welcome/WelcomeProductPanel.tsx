import { useValues } from 'kea'

import { onboardingWelcomeLogic } from './onboardingWelcomeLogic'
import { WelcomeLoading } from './WelcomeLoading'
import { WelcomeProductReady } from './WelcomeProductReady'
import { WelcomeProductStatus } from './WelcomeProductStatus'
import { WelcomeWizardCallout } from './WelcomeWizardCallout'

export function WelcomeProductPanel(): JSX.Element {
    const { selectedProduct, selectedEmptyState } = useValues(onboardingWelcomeLogic)

    if (!selectedProduct || selectedEmptyState === undefined) {
        return <WelcomeLoading />
    }

    const { key, product } = selectedProduct
    return (
        <div className="flex flex-col gap-4">
            <WelcomeWizardCallout />
            {/* Keyed so switching products remounts the next product's detection and celebration. */}
            {selectedEmptyState ? (
                <WelcomeProductStatus key={key} emptyState={selectedEmptyState} product={product} />
            ) : (
                <WelcomeProductReady key={key} product={product} />
            )}
        </div>
    )
}
