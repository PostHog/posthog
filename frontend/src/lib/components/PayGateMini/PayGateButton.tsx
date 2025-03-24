import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useMemo } from 'react'
import { getUpgradeProductLink } from 'scenes/billing/billing-utils'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'
import { urls } from 'scenes/urls'

import { BillingProductV2Type } from '~/types'

import { payGateMiniLogic, PayGateMiniLogicProps } from './payGateMiniLogic'

type PayGateButtonProps = PayGateMiniLogicProps & Partial<LemonButtonProps>
export const PayGateButton = ({ feature, currentUsage, ...buttonProps }: PayGateButtonProps): JSX.Element | null => {
    const { productWithFeature, featureInfo, gateVariant, isAddonProduct, scrollToProduct } = useValues(
        payGateMiniLogic({ feature, currentUsage })
    )
    const { featureFlags } = useValues(featureFlagLogic)

    const { showPaymentEntryModal } = useActions(paymentEntryLogic)

    const ctaLink = useMemo(() => {
        if (gateVariant === 'add-card' && !isAddonProduct) {
            return getUpgradeProductLink({
                product: productWithFeature as BillingProductV2Type,
                // TODO: improve and redirect back to where the cta was shown
                redirectPath: urls.organizationBilling(),
            })
        } else if (gateVariant === 'add-card') {
            return `/organization/billing${scrollToProduct ? `?products=${productWithFeature?.type}` : ''}`
        } else if (gateVariant === 'contact-sales') {
            return `mailto:sales@posthog.com?subject=Inquiring about ${featureInfo?.name}`
        } else if (gateVariant === 'move-to-cloud') {
            return 'https://us.posthog.com/signup?utm_medium=in-product&utm_campaign=move-to-cloud'
        }
        return undefined
    }, [gateVariant, isAddonProduct, productWithFeature, featureInfo, scrollToProduct])

    const ctaLabel = useMemo(() => {
        if (gateVariant === 'add-card') {
            return 'Upgrade now'
        } else if (gateVariant === 'contact-sales') {
            return 'Contact sales'
        }
        return 'Move to PostHog Cloud'
    }, [gateVariant])

    if (
        gateVariant === 'add-card' &&
        !isAddonProduct &&
        featureFlags[FEATURE_FLAGS.BILLING_PAYMENT_ENTRY_IN_APP] == 'test'
    ) {
        return (
            <LemonButton
                type="primary"
                center
                {...buttonProps}
                onClick={(ev) => {
                    showPaymentEntryModal()
                    if (buttonProps.onClick) {
                        buttonProps.onClick(ev)
                    }
                }}
                disableClientSideRouting={true}
            >
                {ctaLabel}
            </LemonButton>
        )
    }

    return (
        <LemonButton
            type="primary"
            center
            {...buttonProps}
            to={ctaLink}
            disableClientSideRouting={gateVariant === 'add-card' && !isAddonProduct}
        >
            {ctaLabel}
        </LemonButton>
    )
}
