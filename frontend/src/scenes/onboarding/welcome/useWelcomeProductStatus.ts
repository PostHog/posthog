import { useValues } from 'kea'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'
import type { ProductSetupStatus } from 'lib/components/ProductEmptyState/types'

import { ProductKey } from '~/queries/schema/schema-general'

import { onboardingWelcomeLogic } from './onboardingWelcomeLogic'

/** The nav badge and the panel read this, so they always agree on whether a product is set up. */
export function useWelcomeProductStatus(productKey: ProductKey): ProductSetupStatus {
    const { pageviewStatus } = useValues(onboardingWelcomeLogic)
    const { status } = useValues(productSetupStatusLogic({ productKey }))
    return productKey === ProductKey.WEB_ANALYTICS ? pageviewStatus : status
}
