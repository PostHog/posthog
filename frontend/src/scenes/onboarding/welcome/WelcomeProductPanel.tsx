import { useValues } from 'kea'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { toSentenceCase } from '../shared/utils'
import { onboardingWelcomeLogic } from './onboardingWelcomeLogic'
import { WelcomeProductDetection } from './WelcomeProductDetection'
import { WelcomeProductReady } from './WelcomeProductReady'
import { WelcomeProductStatus } from './WelcomeProductStatus'
import { WelcomeWizardCallout } from './WelcomeWizardCallout'

export function WelcomeProductPanel(): JSX.Element {
    const { selectedProduct, selectedEmptyState } = useValues(onboardingWelcomeLogic)

    if (!selectedProduct || selectedEmptyState === undefined) {
        return (
            <div className="flex min-h-60 items-center justify-center" role="status" aria-label="Loading">
                <Spinner className="text-2xl" />
            </div>
        )
    }

    const { key, product } = selectedProduct
    // Keyed so switching products remounts the next product's detection and celebration.
    const content = selectedEmptyState ? (
        <WelcomeProductStatus key={key} emptyState={selectedEmptyState} product={product} />
    ) : (
        <WelcomeProductReady
            key={key}
            product={product}
            title={toSentenceCase(product.name)}
            description={product.userCentricDescription ?? product.description}
        />
    )

    return (
        <div className="flex flex-col gap-4">
            <WelcomeWizardCallout />
            {selectedEmptyState?.statusLogic ? (
                <WelcomeProductDetection key={key} statusLogic={selectedEmptyState.statusLogic}>
                    {content}
                </WelcomeProductDetection>
            ) : (
                content
            )}
        </div>
    )
}
