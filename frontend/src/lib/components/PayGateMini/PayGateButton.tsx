import { LemonButton } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'

import { BillingFeatureType, BillingProductV2AddonType, BillingProductV2Type } from '~/types'

interface PayGateButtonProps {
    gateVariant: 'add-card' | 'contact-sales' | 'move-to-cloud' | null
    productWithFeature: BillingProductV2AddonType | BillingProductV2Type
    featureInfo: BillingFeatureType
    onCtaClick: () => void
    isAddonProduct?: boolean
    scrollToProduct: boolean
}

export const PayGateButton = ({
    gateVariant,
    productWithFeature,
    featureInfo,
    onCtaClick,
    isAddonProduct,
    scrollToProduct = true,
}: PayGateButtonProps): JSX.Element => {
    return (
        <LemonButton
            to={getCtaLink(gateVariant, productWithFeature, featureInfo, isAddonProduct, scrollToProduct)}
            disableClientSideRouting={gateVariant === 'add-card' && !isAddonProduct}
            type="primary"
            center
            onClick={onCtaClick}
        >
            {getCtaLabel(gateVariant)}
        </LemonButton>
    )
}

const getCtaLink = (
    gateVariant: 'add-card' | 'contact-sales' | 'move-to-cloud' | null,
    productWithFeature: BillingProductV2AddonType | BillingProductV2Type,
    featureInfo: BillingFeatureType,
    isAddonProduct?: boolean,
    scrollToProduct: boolean = true
): string | undefined => {
    if (gateVariant === 'add-card' && !isAddonProduct) {
        return `/api/billing/activate?products=all_products:&redirect_path=${urls.organizationBilling()}&intent_product=${
            productWithFeature.type
        }`
    } else if (gateVariant === 'add-card') {
        return `/organization/billing${scrollToProduct ? `?products=${productWithFeature.type}` : ''}`
    } else if (gateVariant === 'contact-sales') {
        return `mailto:sales@posthog.com?subject=Inquiring about ${featureInfo.name}`
    } else if (gateVariant === 'move-to-cloud') {
        return 'https://us.posthog.com/signup?utm_medium=in-product&utm_campaign=move-to-cloud'
    }
    return undefined
}

const getCtaLabel = (gateVariant: 'add-card' | 'contact-sales' | 'move-to-cloud' | null): string => {
    if (gateVariant === 'add-card') {
        return 'Upgrade now'
    } else if (gateVariant === 'contact-sales') {
        return 'Contact sales'
    }
    return 'Move to PostHog Cloud'
}
