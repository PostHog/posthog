import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { PlanComparisonModal } from 'scenes/billing/PlanComparison'
import { urls } from 'scenes/urls'

import { BillingProductV2AddonType, BillingProductV2Type, BillingV2FeatureType } from '~/types'

export const PayGateMiniButton = ({
    product,
    gateVariant,
    featureInfo,
    onClick,
}: {
    product: BillingProductV2Type | BillingProductV2AddonType
    featureInfo: BillingV2FeatureType
    gateVariant: 'add-card' | 'contact-sales' | 'move-to-cloud'
    onClick?: () => void
}): JSX.Element => {
    const { isPlanComparisonModalOpen } = useValues(billingProductLogic({ product }))
    const { toggleIsPlanComparisonModalOpen } = useActions(billingProductLogic({ product }))

    // We know that the product is a BillingProductV2Type because that's the only
    // type that can be used here from the PayGateMini component. But TypeScript doesn't
    // know that, so we need to cast it to the correct type, and it's simpler to do this
    // here than in the PayGateMini component.
    const typedProduct = product as BillingProductV2Type

    return (
        <>
            <LemonButton
                to={
                    gateVariant === 'contact-sales'
                        ? `mailto:sales@posthog.com?subject=Inquiring about ${featureInfo.name}`
                        : gateVariant === 'move-to-cloud'
                        ? urls.moveToPostHogCloud()
                        : undefined
                }
                type="primary"
                center
                onClick={() => {
                    if (gateVariant === 'add-card') {
                        toggleIsPlanComparisonModalOpen(featureInfo.key)
                    }
                    posthog.capture('pay gate CTA clicked', {
                        product_key: product?.type,
                        feature: featureInfo.key,
                        gate_variant: gateVariant,
                    })
                    onClick?.()
                }}
            >
                {gateVariant === 'add-card'
                    ? `Compare plans`
                    : gateVariant === 'contact-sales'
                    ? 'Contact sales'
                    : 'Move to PostHog Cloud'}
            </LemonButton>
            <PlanComparisonModal
                key={`modal-${featureInfo.key}`}
                product={typedProduct}
                modalOpen={isPlanComparisonModalOpen}
                onClose={() => toggleIsPlanComparisonModalOpen()}
            />
        </>
    )
}
