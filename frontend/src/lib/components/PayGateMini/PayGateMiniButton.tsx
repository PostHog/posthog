import { LemonButton } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'
import { PlanComparisonModal } from 'scenes/billing/PlanComparison'
import { urls } from 'scenes/urls'

import { BillingProductV2Type, BillingV2FeatureType } from '~/types'

export const PayGateMiniButton = ({
    product,
    gateVariant,
    featureInfo,
    onClick,
}: {
    product: BillingProductV2Type
    featureInfo: BillingV2FeatureType
    gateVariant: 'add-card' | 'contact-sales' | 'move-to-cloud'
    onClick?: () => void
}): JSX.Element => {
    const { isPlanComparisonModalOpen } = useValues(billingProductLogic({ product }))
    const { toggleIsPlanComparisonModalOpen } = useActions(billingProductLogic({ product }))

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
                product={product}
                modalOpen={isPlanComparisonModalOpen}
                onClose={() => toggleIsPlanComparisonModalOpen()}
            />
        </>
    )
}
