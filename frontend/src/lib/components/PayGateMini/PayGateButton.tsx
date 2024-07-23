import { LemonButton, LemonButtonProps } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { useMemo } from 'react'
import { urls } from 'scenes/urls'

import { payGateMiniLogic, PayGateMiniLogicProps } from './payGateMiniLogic'

type PayGateButtonProps = PayGateMiniLogicProps & Partial<LemonButtonProps>
export const PayGateButton = ({ feature, currentUsage, ...buttonProps }: PayGateButtonProps): JSX.Element | null => {
    const { productWithFeature, featureInfo, gateVariant, isAddonProduct, scrollToProduct } = useValues(
        payGateMiniLogic({ feature, currentUsage })
    )

    const ctaLink = useMemo(() => {
        if (gateVariant === 'add-card' && !isAddonProduct) {
            return `/api/billing/activate?products=all_products:&redirect_path=${urls.organizationBilling()}&intent_product=${
                productWithFeature?.type
            }`
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
