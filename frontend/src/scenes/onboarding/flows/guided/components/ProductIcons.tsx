import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { availableOnboardingProducts, getProductIcon, toSentenceCase } from 'lib/onboarding/utils'

import { ProductKey } from '~/queries/schema/schema-general'

/** The products behind a goal as small icons, named on hover. */
export function ProductIcons({ productKeys }: { productKeys: ProductKey[] }): JSX.Element {
    return (
        <span className="flex shrink-0 items-center gap-1.5">
            {productKeys.map((productKey) => {
                const product = availableOnboardingProducts[productKey as keyof typeof availableOnboardingProducts]
                if (!product) {
                    return null
                }
                const name = toSentenceCase(product.name)
                return (
                    <Tooltip key={productKey}>
                        <TooltipTrigger render={<span className="flex text-sm" />} aria-label={name}>
                            {getProductIcon(product.icon, { iconColor: product.iconColor, productType: productKey })}
                        </TooltipTrigger>
                        <TooltipContent>{name}</TooltipContent>
                    </Tooltip>
                )
            })}
        </span>
    )
}
