import { LemonModal } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils'

import { BillingPlanType, BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import { getTierDescription } from './BillingProduct'

export const ProductPricingModal = ({
    product,
    planKey,
    modalOpen,
    onClose,
}: {
    product: BillingProductV2Type | BillingProductV2AddonType
    planKey?: string
    modalOpen: boolean
    onClose?: () => void
}): JSX.Element | null => {
    if (!planKey) {
        return null
    }
    const tiers = product?.plans?.find((plan: BillingPlanType) => plan.plan_key === planKey)?.tiers

    if (!product || !tiers) {
        return null
    }
    const isFirstTierFree = parseFloat(tiers[0]?.unit_amount_usd) === 0
    const numberOfSigFigs = tiers.map((tier) => tier.unit_amount_usd?.split('.')[1]?.length).sort((a, b) => b - a)[0]

    return (
        <LemonModal isOpen={modalOpen} onClose={onClose}>
            <div className="flex items-center w-full h-full justify-center p-8">
                <div className="text-left bg-surface-primary rounded relative w-full">
                    <h5 className="text-gray mb-1">{capitalizeFirstLetter(product.name)} pricing, starting at</h5>
                    <p className="mb-1">
                        <span className="font-bold text-base">
                            $
                            {parseFloat(
                                isFirstTierFree && tiers?.[1]?.unit_amount_usd
                                    ? tiers?.[1]?.unit_amount_usd
                                    : tiers?.[0]?.unit_amount_usd
                            ).toFixed(numberOfSigFigs)}
                        </span>
                        {/* the product types we have are plural, so we need to singularlize them and this works for now */}
                        <span className="text-gray">/{product.unit}</span>
                    </p>
                    {isFirstTierFree && (
                        <p className="text-gray">{getTierDescription(tiers, 0, product, 'month')} free</p>
                    )}
                    <div>
                        <h4 className="font-bold">Volume discounts</h4>
                        <div className="">
                            {tiers.map((tier, i) => {
                                return (
                                    <div
                                        key={`tiers-modal-${product.name}-tier-${i}`}
                                        className="flex justify-between border-b border-primary border-dashed py-1 gap-x-8"
                                    >
                                        <p className="col-span-1 mb-0">
                                            {getTierDescription(tiers, i, product, 'month')}
                                        </p>
                                        <p className="font-bold mb-0 ">
                                            {isFirstTierFree && i === 0
                                                ? 'Free'
                                                : `$${parseFloat(tier.unit_amount_usd).toFixed(numberOfSigFigs)}`}
                                        </p>
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                </div>
            </div>
        </LemonModal>
    )
}
