import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { ProductKey } from '~/queries/schema/schema-general'
import type { OnboardingProduct } from '~/types'

import { getProductIcon, toSentenceCase } from '../shared/utils'
import { useWelcomeProductStatus } from './useWelcomeProductStatus'

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
    const status = useWelcomeProductStatus(productKey)

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
