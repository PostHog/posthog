import { useValues } from 'kea'

import { ProductEmptyState } from 'lib/components/ProductEmptyState/ProductEmptyState'
import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { OnboardingProduct } from '~/types'

import { toSentenceCase } from '../shared/utils'
import { onboardingWelcomeLogic } from './onboardingWelcomeLogic'
import { WelcomeCelebration } from './WelcomeCelebration'
import type { WelcomeEmptyState } from './welcomeEmptyState'
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
    const { statusOverrides } = useValues(onboardingWelcomeLogic)
    const { status: sharedStatus } = useValues(productSetupStatusLogic({ productKey }))
    const status = statusOverrides[productKey] ?? sharedStatus
    const name = toSentenceCase(product.name)

    if (status === 'loading') {
        return (
            <div className="flex min-h-60 items-center justify-center" role="status" aria-label="Loading">
                <Spinner className="text-2xl" />
            </div>
        )
    }
    if (status === 'has-data') {
        return (
            <>
                <WelcomeCelebration productKey={productKey} />
                <WelcomeProductReady
                    product={product}
                    title={`${name} is set up`}
                    description="This project is already using it."
                />
            </>
        )
    }
    if (status === 'unknown') {
        return (
            <WelcomeProductReady
                product={product}
                title={name}
                description={product.userCentricDescription ?? product.description}
            />
        )
    }
    return (
        // Skipping would only hide the setup screen in the product's own scene, so this page drops it.
        <ProductEmptyState config={{ ...emptyState.config, skippable: false }} mode={status} />
    )
}
