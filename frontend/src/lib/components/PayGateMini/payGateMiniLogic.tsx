import { actions, connect, kea, key, path, props, reducers, selectors } from 'kea'

import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { billingLogic } from 'scenes/billing/billingLogic'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature, BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import type { payGateMiniLogicType } from './payGateMiniLogicType'

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
        ctaLink: [
            (s) => [s.gateVariant, s.productWithFeature, s.featureInfo],
            (gateVariant, productWithFeature, featureInfo) => {
                // product activation is already handled in the startPaymentEntryFlow,
                // ctaLink is used only when isPaymentEntryFlow is false
                if (gateVariant === 'add-card') {
                    return `/organization/billing${productWithFeature?.type ? `?products=${productWithFeature.type}` : ''}`
                } else if (gateVariant === 'contact-sales') {
                    return `mailto:sales@posthog.com?subject=Inquiring about ${featureInfo?.name}`
                } else if (gateVariant === 'move-to-cloud') {
                    return 'https://us.posthog.com/signup?utm_medium=in-product&utm_campaign=move-to-cloud'
                }
                return undefined
            },
        ],
        ctaLabel: [
            (s) => [s.gateVariant, s.isPaymentEntryFlow],
            (gateVariant, isPaymentEntryFlow) => {
                if (gateVariant === 'contact-sales') {
                    return 'Contact sales'
                }
                if (gateVariant === 'move-to-cloud') {
                    return 'Move to PostHog Cloud'
                }
                if (isPaymentEntryFlow) {
                    return 'Upgrade now'
                }
                if (gateVariant === 'add-card') {
                    return 'View plans'
                }
                return 'Upgrade now'
            },
        ],
        isPaymentEntryFlow: [
            (s) => [s.gateVariant, s.isAddonProduct, s.billing],
            (gateVariant, isAddonProduct, billing): boolean => {
                // Show payment entry flow only for free customers trying to upgrade to a paid plan
                // to use core features (not addons)
                return gateVariant === 'add-card' && !isAddonProduct && billing?.subscription_level === 'free'
            },
        ],
    })),
])
