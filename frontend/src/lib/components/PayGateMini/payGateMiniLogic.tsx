import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { getUpgradeProductLink } from 'scenes/billing/billing-utils'
import { billingLogic } from 'scenes/billing/billingLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import type { payGateMiniLogicType } from './payGateMiniLogicType'

// Feature flag payload for PLATFORM_PAYGATE_CTA
interface PaygateCtaFlagPayload {
    freeUsersCTA?: string
    trialEligibleCTA?: string
    trialUsedCTA?: string
}

export interface PayGateMiniLogicProps {
    feature: AvailableFeature
    currentUsage?: number
}

export type GateVariantType = 'add-card' | 'contact-sales' | 'move-to-cloud' | null

export const payGateMiniLogic = kea<payGateMiniLogicType>([
    props({} as PayGateMiniLogicProps),
    path(['lib', 'components', 'payGateMini', 'payGateMiniLogic']),
    key((props) => props.feature),
    connect(() => ({
        values: [
            billingLogic,
            ['billing', 'billingLoading'],
            userLogic,
            ['user', 'hasAvailableFeature', 'availableFeature'],
            preflightLogic,
            ['isCloudOrDev'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [],
    })),
    reducers({
        bypassPaywall: [
            false,
            {
                setBypassPaywall: (_, { bypassPaywall }) => bypassPaywall,
            },
        ],
        addonTrialModalOpen: [
            false,
            {
                openAddonTrialModal: () => true,
                closeAddonTrialModal: () => false,
            },
        ],
    }),
    actions({
        setGateVariant: (gateVariant: GateVariantType) => ({ gateVariant }),
        setBypassPaywall: (bypassPaywall: boolean) => ({ bypassPaywall }),
        openAddonTrialModal: true,
        closeAddonTrialModal: true,
    }),
    selectors(({ values, props }) => ({
        productWithFeature: [
            (s) => [s.billing],
            (billing) => {
                // TODO(@zach): revisit this logic after subscribe to all products is released
                // There are some features where we want to check the product first
                const checkProductFirst = [AvailableFeature.ORGANIZATIONS_PROJECTS, AvailableFeature.ENVIRONMENTS]

                let foundProduct: BillingProductV2Type | BillingProductV2AddonType | undefined = undefined

                if (checkProductFirst.includes(props.feature)) {
                    foundProduct = billing?.products
                        .filter((plan) => !plan.legacy_product || plan.subscribed)
                        .find((product) => product.features?.some((f) => f.key === props.feature))
                }

                // Check addons first (if not included in checkProductFirst) since their features are rolled up into the parent
                const allAddons = billing?.products?.map((product) => product.addons).flat() || []
                if (!foundProduct) {
                    foundProduct = allAddons
                        .filter((plan) => !plan.legacy_product || plan.subscribed)
                        .find((addon) => addon.features?.some((f) => f.key === props.feature))
                }

                if (!foundProduct) {
                    foundProduct = billing?.products
                        .filter((plan) => !plan.legacy_product || plan.subscribed)
                        .find((product) => product.features?.some((f) => f.key === props.feature))
                }
                return foundProduct
            },
        ],
        isAddonProduct: [
            (s) => [s.billing, s.productWithFeature],
            (billing, productWithFeature) =>
                billing?.products?.some((product) =>
                    product.addons?.some((addon) => addon.type === productWithFeature?.type)
                ),
        ],
        featureInfo: [
            (s) => [s.productWithFeature],
            (productWithFeature) => productWithFeature?.features.find((f) => f.key === props.feature),
        ],
        featureAvailableOnOrg: [
            (s) => [s.user, (_, props) => props.feature],
            (_user, feature) => {
                return values.availableFeature(feature)
            },
        ],
        minimumPlanWithFeature: [
            (s) => [s.productWithFeature],
            (productWithFeature) =>
                productWithFeature?.plans.find((plan) => plan.features?.some((f) => f.key === props.feature)),
        ],
        nextPlanWithFeature: [
            (s) => [s.productWithFeature],
            (productWithFeature) => {
                const currentPlanIndex = productWithFeature?.plans.findIndex((plan) => plan.current_plan)
                if (currentPlanIndex === undefined || currentPlanIndex < 0) {
                    return null
                }
                return productWithFeature?.plans[currentPlanIndex + 1]
            },
        ],
        featureInfoOnNextPlan: [
            (s) => [s.nextPlanWithFeature],
            (nextPlanWithFeature) => nextPlanWithFeature?.features.find((f) => f.key === props.feature),
        ],
        isTrialEligible: [
            (s) => [s.productWithFeature, s.billing],
            (productWithFeature, billing) => {
                return !billing?.trial && !!productWithFeature?.trial
            },
        ],
        gateVariant: [
            (s) => [
                s.billingLoading,
                s.hasAvailableFeature,
                s.minimumPlanWithFeature,
                (_, props) => props.feature,
                (_, props) => props.currentUsage,
            ],
            (billingLoading, hasAvailableFeature, minimumPlanWithFeature, feature, currentUsage) => {
                if (hasAvailableFeature(feature, currentUsage)) {
                    return null
                }
                if (billingLoading) {
                    return null
                }
                if (values.isCloudOrDev) {
                    if (!minimumPlanWithFeature || minimumPlanWithFeature.contact_support) {
                        return 'contact-sales'
                    }
                    return 'add-card'
                }
                return 'move-to-cloud'
            },
        ],

        scrollToProduct: [
            (s) => [s.featureInfo, s.isAddonProduct],
            (featureInfo, isAddonProduct) => {
                return !(featureInfo?.key === AvailableFeature.ORGANIZATIONS_PROJECTS && !isAddonProduct)
            },
        ],
        ctaLink: [
            (s) => [s.gateVariant, s.isAddonProduct, s.productWithFeature, s.featureInfo, s.scrollToProduct],
            (gateVariant, isAddonProduct, productWithFeature, featureInfo, scrollToProduct) => {
                if (gateVariant === 'add-card' && !isAddonProduct && productWithFeature) {
                    return getUpgradeProductLink({
                        product: productWithFeature as BillingProductV2Type,
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
            },
        ],
        ctaLabel: [
            (s) => [s.gateVariant, s.billing, s.isTrialEligible, s.featureFlags],
            (gateVariant, billing, isTrialEligible, featureFlags) => {
                if (gateVariant === 'contact-sales') {
                    return 'Contact sales'
                }
                if (gateVariant === 'move-to-cloud') {
                    return 'Move to PostHog Cloud'
                }

                // Trigger $feature_flag_called for analytics
                void featureFlags[FEATURE_FLAGS.PLATFORM_PAYGATE_CTA]

                const isPaidOrg = billing?.subscription_level !== 'free'
                const payload = posthog.getFeatureFlagPayload(FEATURE_FLAGS.PLATFORM_PAYGATE_CTA) as
                    | PaygateCtaFlagPayload
                    | undefined

                if (!isPaidOrg && payload?.freeUsersCTA) {
                    return payload.freeUsersCTA
                }
                if (isTrialEligible && payload?.trialEligibleCTA) {
                    return payload.trialEligibleCTA
                }
                if (!isTrialEligible && payload?.trialUsedCTA) {
                    return payload.trialUsedCTA
                }

                if (gateVariant === 'add-card') {
                    return 'Upgrade now'
                }
                return 'Upgrade now'
            },
        ],
        isPaymentEntryFlow: [
            (s) => [s.gateVariant, s.isAddonProduct],
            (gateVariant, isAddonProduct): boolean => gateVariant === 'add-card' && !isAddonProduct,
        ],
    })),
])
