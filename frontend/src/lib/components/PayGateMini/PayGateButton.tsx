import { LemonButton } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic, FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { BillingFeatureType, BillingProductV2AddonType, BillingProductV2Type, BillingType } from '~/types'

interface PayGateButtonProps {
    gateVariant: 'add-card' | 'contact-sales' | 'move-to-cloud' | null
    productWithFeature: BillingProductV2AddonType | BillingProductV2Type
    featureInfo: BillingFeatureType
    onCtaClick: () => void
    billing: BillingType | null
    isAddonProduct?: boolean
    scrollToProduct: boolean
}

export const PayGateButton = ({
    gateVariant,
    productWithFeature,
    featureInfo,
    onCtaClick,
    billing,
    isAddonProduct,
    scrollToProduct = true,
}: PayGateButtonProps): JSX.Element => {
    const { featureFlags } = useValues(featureFlagLogic)
    return (
        <LemonButton
            to={getCtaLink(
                gateVariant,
                productWithFeature,
                featureInfo,
                featureFlags,
                billing?.subscription_level,
                isAddonProduct,
                scrollToProduct
            )}
            disableClientSideRouting={gateVariant === 'add-card' && !isAddonProduct}
            type="primary"
            center
            onClick={onCtaClick}
        >
            {getCtaLabel(gateVariant, billing, featureFlags)}
        </LemonButton>
    )
}

const getCtaLink = (
    gateVariant: 'add-card' | 'contact-sales' | 'move-to-cloud' | null,
    productWithFeature: BillingProductV2AddonType | BillingProductV2Type,
    featureInfo: BillingFeatureType,
    featureFlags: FeatureFlagsSet,
    subscriptionLevel?: BillingType['subscription_level'],
    isAddonProduct?: boolean,
    scrollToProduct: boolean = true
): string | undefined => {
    if (
        gateVariant === 'add-card' &&
        !isAddonProduct &&
        featureFlags[FEATURE_FLAGS.SUBSCRIBE_TO_ALL_PRODUCTS] === 'test' &&
        subscriptionLevel === 'free'
    ) {
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

const getCtaLabel = (
    gateVariant: 'add-card' | 'contact-sales' | 'move-to-cloud' | null,
    billing: BillingType | null,
    featureFlags: FeatureFlagsSet
): string => {
    if (
        gateVariant === 'add-card' &&
        featureFlags[FEATURE_FLAGS.SUBSCRIBE_TO_ALL_PRODUCTS] === 'test' &&
        billing?.subscription_level === 'free'
    ) {
        return 'Upgrade now'
    } else if (gateVariant === 'add-card') {
        return billing?.has_active_subscription ? 'Upgrade now' : 'Subscribe now'
    } else if (gateVariant === 'contact-sales') {
        return 'Contact sales'
    }
    return 'Move to PostHog Cloud'
}
