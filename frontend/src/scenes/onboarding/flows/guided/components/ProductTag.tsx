import { Badge } from '@posthog/quill'

import { availableOnboardingProducts, getProductIcon, toSentenceCase } from 'lib/onboarding/utils'

import { ProductKey } from '~/queries/schema/schema-general'

export function ProductTag({ productKey }: { productKey: ProductKey }): JSX.Element | null {
    const product = availableOnboardingProducts[productKey as keyof typeof availableOnboardingProducts]
    if (!product) {
        return null
    }
    return (
        <Badge>
            {getProductIcon(product.icon, { iconColor: product.iconColor, productType: productKey })}
            {toSentenceCase(product.name)}
        </Badge>
    )
}
