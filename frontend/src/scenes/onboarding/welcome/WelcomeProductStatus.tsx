import { ProductEmptyState } from 'lib/components/ProductEmptyState/ProductEmptyState'

import type { OnboardingProduct } from '~/types'

import { toSentenceCase } from '../shared/utils'
import { useWelcomeProductStatus } from './useWelcomeProductStatus'
import { WelcomeCelebration } from './WelcomeCelebration'
import type { WelcomeEmptyState } from './welcomeEmptyState'
import { WelcomeLoading } from './WelcomeLoading'
import { WelcomeProductDetection } from './WelcomeProductDetection'
import { WelcomeProductReady } from './WelcomeProductReady'

/**
 * The product's own setup screen until it has data, then a way into it. Reads the same status as the
 * product's scene gate, so both surfaces agree on whether the product is set up.
 */
export function WelcomeProductStatus({
    emptyState,
    product,
}: {
    emptyState: WelcomeEmptyState
    product: OnboardingProduct
}): JSX.Element {
    const productKey = emptyState.config.productKey
    const status = useWelcomeProductStatus(productKey)

    return (
        <>
            {emptyState.statusLogic ? <WelcomeProductDetection statusLogic={emptyState.statusLogic} /> : null}
            {status === 'loading' ? (
                <WelcomeLoading />
            ) : status === 'has-data' ? (
                <>
                    <WelcomeCelebration productKey={productKey} />
                    <WelcomeProductReady
                        product={product}
                        title={`${toSentenceCase(product.name)} is set up`}
                        description="This project is already using it."
                    />
                </>
            ) : status === 'unknown' ? (
                <WelcomeProductReady product={product} />
            ) : (
                // Skipping would only hide the setup screen in the product's own scene, so this page drops it.
                <ProductEmptyState config={{ ...emptyState.config, skippable: false }} mode={status} />
            )}
        </>
    )
}
