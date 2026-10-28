import { useValues } from 'kea'

import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import type { OnboardingProduct } from '~/types'

import { getProductIcon, toSentenceCase } from '../shared/utils'

export function WelcomeProductNavItem({
    productKey,
    product,
    active,
    onSelect,
}: {
    productKey: ProductKey
    product: OnboardingProduct
    active: boolean
    onSelect: () => void
}): JSX.Element {
    const { status } = useValues(productSetupStatusLogic({ productKey }))

    return (
        <LemonButton
            className="@min-[56rem]/main-content:w-full"
            active={active}
            icon={getProductIcon(product.icon, { iconColor: product.iconColor })}
            sideIcon={
                status === 'has-data' ? (
                    <LemonTag type="success" size="small">
                        Installed
                    </LemonTag>
                ) : undefined
            }
            tooltip={product.description}
            tooltipPlacement="right"
            onClick={onSelect}
            data-attr={`onboarding-welcome-product-${productKey}`}
        >
            {toSentenceCase(product.name)}
        </LemonButton>
    )
}
