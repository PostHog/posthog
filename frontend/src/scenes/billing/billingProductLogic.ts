import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import posthog from 'posthog-js'
import React from 'react'

import { LemonDialog, lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { dayjs } from 'lib/dayjs'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    BillingPlan,
    BillingPlanType,
    BillingProductV2AddonType,
    BillingProductV2Type,
    BillingType,
    SurveyEventName,
} from '~/types'

import { calculateFreeTier, createGaugeItems, isAddonVisible, isProductVariantPrimary } from './billing-utils'
import { billingLogic } from './billingLogic'
import type { billingProductLogicType } from './billingProductLogicType'
import { DATA_PIPELINES_CUTOFF_DATE } from './constants'
import { BillingGaugeItemKind, BillingGaugeItemType } from './types'

const DEFAULT_BILLING_LIMIT: number = 500

type UnsubscribeReason = {
    reason: string
    question: string
}

export const UNSUBSCRIBE_REASONS: UnsubscribeReason[] = [
    { reason: 'Too expensive', question: 'What will you be using instead?' },
    { reason: 'Not getting enough value', question: 'What prevented you from getting more value out of PostHog?' },
    { reason: 'Not using the product', question: 'Why are you not using the product?' },
    { reason: 'Found a better alternative', question: 'What service will you be moving to?' },
    { reason: 'Poor customer support', question: 'Please provide details on your support experience.' },
    { reason: 'Too difficult to use', question: 'What was difficult to use?' },
    { reason: 'Not enough hedgehogs', question: 'How many hedgehogs do you need? (but really why are you leaving)' },
    { reason: 'Shutting down company', question: "We're sorry to hear that ❤️. What was your favorite feature?" },
    { reason: 'Technical issues', question: 'What technical problems did you experience?' },
    { reason: 'Other (let us know below!)', question: 'Why are you leaving?' },
]

export const randomizeReasons = (reasons: UnsubscribeReason[]): UnsubscribeReason[] => {
    const shuffledReasons = reasons.slice(0, -1).sort(() => Math.random() - 0.5)
    shuffledReasons.push(reasons[reasons.length - 1])
    return shuffledReasons
}

export const TRIAL_CANCEL_REASONS: UnsubscribeReason[] = [
    { reason: 'Too expensive', question: 'What budget would make sense?' },
    { reason: 'Trial too short', question: 'How long would be enough to try the add-on features?' },
    { reason: 'Complex setup', question: 'Which part of the setup was challenging?' },
    { reason: 'Found a better alternative', question: 'Which alternative are you going with?' },
    { reason: "Don't need add-on features", question: 'Which features did you not need?' },
    { reason: 'Poor customer support', question: 'Please provide details on your support experience.' },
    { reason: 'Other', question: 'What should we know?' },
]

export const isPlatformAndSupportAddon = (product: BillingProductV2Type | BillingProductV2AddonType): boolean => {
    return (
        product.type === BillingPlan.Boost ||
        product.type === BillingPlan.Teams ||
        product.type === BillingPlan.Scale ||
        product.type === BillingPlan.Enterprise
    )
}

export interface BillingProductLogicProps {
    product: BillingProductV2Type | BillingProductV2AddonType
    productRef?: React.MutableRefObject<HTMLDivElement | null>
    billingLimitInputRef?: React.MutableRefObject<HTMLInputElement | null>
    hogfettiTrigger?: () => void
}

export const billingProductLogic = kea<billingProductLogicType>([
    props({} as BillingProductLogicProps),
    key((props) => props.product.type),
    path(['scenes', 'billing', 'billingProductLogic']),
    connect(() => ({
        values: [
            billingLogic,
            [
                'billing',
                'isUnlicensedDebug',
                'scrollToProductKey',
                'unsubscribeError',
                'currentPlatformAddon',
                'platformAddons',
                'timeRemainingInSeconds',
                'timeTotalInSeconds',
            ],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            billingLogic,
            [
                'updateBillingLimits',
                'updateBillingLimitsSuccess',
                'loadBilling',
                'loadBillingSuccess',
                'deactivateProduct',
                'setProductSpecificAlert',
                'setScrollToProductKey',
                'deactivateProductSuccess',
                'switchFlatrateSubscriptionPlan',
                'setSwitchPlanLoading',
            ],
        ],
    })),
    actions({
        setIsEditingBillingLimit: (isEditingBillingLimit: boolean) => ({ isEditingBillingLimit }),
        setBillingLimitInput: (billingLimitInput: number | null) => ({ billingLimitInput }),
        billingLoaded: true,
        setShowTierBreakdown: (showTierBreakdown: boolean) => ({ showTierBreakdown }),
        toggleVariantExpanded: (variantKey: string) => ({ variantKey }),
        toggleIsPricingModalOpen: true,
        toggleIsPlanComparisonModalOpen: (highlightedFeatureKey?: string) => ({ highlightedFeatureKey }),
        setSurveyResponse: (key: string, value: string | string[]) => ({ key, value }),
        toggleSurveyReason: (reason: string) => ({ reason }),
        reportSurveyShown: (surveyID: string, productType: string) => ({ surveyID, productType }),
        reportSurveySent: (surveyID: string, surveyResponse: Record<string, string | string[]>) => ({
            surveyID,
            surveyResponse,
        }),
        reportSurveyDismissed: (surveyID: string) => ({ surveyID }),
        setSurveyID: (surveyID: string) => ({ surveyID }),
        setBillingProductLoading: (productKey: string | null) => ({ productKey }),
        initiateProductUpgrade: (
            product: BillingProductV2Type | BillingProductV2AddonType,
            plan: BillingPlanType,
            redirectPath?: string
        ) => ({
            plan,
            product,
            redirectPath,
        }),
        handleProductUpgrade: (products: string, redirectPath?: string) => ({
            products,
            redirectPath,
        }),
        activateTrial: true,
        cancelTrial: true,
        setTrialLoading: (loading: boolean) => ({ loading }),
        setUnsubscribeModalStep: (step: number) => ({ step }),
        resetUnsubscribeModalStep: true,
        setHedgehogSatisfied: (satisfied: boolean) => ({ satisfied }),
        triggerMoreHedgehogs: true,
        removeBillingLimitNextPeriod: (productType: string) => ({ productType }),
        showConfirmUpgradeModal: true,
        hideConfirmUpgradeModal: true,
        confirmProductUpgrade: true,
        showConfirmDowngradeModal: true,
        hideConfirmDowngradeModal: true,
        confirmProductDowngrade: true,
    }),
    reducers({
        billingLimitInput: [
            { input: DEFAULT_BILLING_LIMIT },
            {
                setBillingLimitInput: (_, { billingLimitInput }) => {
                    return {
                        input: billingLimitInput,
                    }
                },
            },
        ],
        isEditingBillingLimit: [
            false,
            {
                setIsEditingBillingLimit: (_, { isEditingBillingLimit }) => isEditingBillingLimit,
            },
        ],
        showTierBreakdown: [
            false,
            {
                setShowTierBreakdown: (_, { showTierBreakdown }) => showTierBreakdown,
            },
        ],
        variantExpandedStates: [
            {} as Record<string, boolean>,
            {
                toggleVariantExpanded: (state, { variantKey }) => ({
                    ...state,
                    [variantKey]: !state[variantKey],
                }),
            },
        ],
        isPricingModalOpen: [
            false as boolean,
            {
                toggleIsPricingModalOpen: (state) => !state,
            },
        ],
        isPlanComparisonModalOpen: [
            false as boolean,
            {
                toggleIsPlanComparisonModalOpen: (state) => !state,
            },
        ],
        surveyResponse: [
            { $survey_response_2: [], $survey_response: '' } as {
                $survey_response_2: string[]
                $survey_response: string
            },
            {
                setSurveyResponse: (state, { key, value }) => {
                    return { ...state, [key]: value }
                },
                toggleSurveyReason: (state, { reason }) => {
                    const reasons = state.$survey_response_2.includes(reason)
                        ? state.$survey_response_2.filter((r) => r !== reason)
                        : [...state.$survey_response_2, reason]
                    return { ...state, $survey_response_2: reasons }
                },
            },
        ],
        unsubscribeReasonSurvey: [
            null,
            {
                setUnsubscribeReasonSurvey: (_, { survey }) => survey,
            },
        ],
        surveyID: [
            '',
            {
                setSurveyID: (_, { surveyID }) => surveyID,
            },
        ],
        billingProductLoading: [
            null as string | null,
            {
                setBillingProductLoading: (_, { productKey }) => productKey,
            },
        ],
        comparisonModalHighlightedFeatureKey: [
            null as string | null,
            {
                toggleIsPlanComparisonModalOpen: (_, { highlightedFeatureKey }) => highlightedFeatureKey || null,
            },
        ],
        trialLoading: [
            false,
            {
                setTrialLoading: (_, { loading }) => loading,
            },
        ],
        unsubscribeModalStep: [
            1 as number,
            {
                setUnsubscribeModalStep: (_, { step }) => step,
                resetUnsubscribeModalStep: () => 1,
            },
        ],
        hedgehogSatisfied: [
            false as boolean,
            {
                setHedgehogSatisfied: (_, { satisfied }) => satisfied,
            },
        ],
        confirmUpgradeModalOpen: [
            false as boolean,
            {
                showConfirmUpgradeModal: () => true,
                hideConfirmUpgradeModal: () => false,
            },
        ],
        confirmDowngradeModalOpen: [
            false as boolean,
            {
                showConfirmDowngradeModal: () => true,
                hideConfirmDowngradeModal: () => false,
            },
        ],
    }),
    selectors(({ values }) => ({
        proratedAmount: [
            (s) => [s.currentAndUpgradePlans, s.timeRemainingInSeconds, s.timeTotalInSeconds],
            (currentAndUpgradePlans, timeRemainingInSeconds, timeTotalInSeconds): number => {
                if (!timeTotalInSeconds) {
                    return 0
                }
                const amountUsd = currentAndUpgradePlans.upgradePlan?.unit_amount_usd
                const unitAmountInt = amountUsd ? parseFloat(amountUsd) : 0
                const ratio = Math.max(0, Math.min(1, timeRemainingInSeconds / timeTotalInSeconds)) // make sure ratio is between 0 and 1
                return Math.round(unitAmountInt * ratio * 100) / 100
            },
        ],
        isProrated: [
            (s) => [s.billing, s.currentAndUpgradePlans, s.proratedAmount],
            (billing, currentAndUpgradePlans, proratedAmount): boolean => {
                const hasActiveSubscription = billing?.has_active_subscription
                const amountUsd = currentAndUpgradePlans.upgradePlan?.unit_amount_usd
                if (!hasActiveSubscription || !amountUsd) {
                    return false
                }
                return proratedAmount !== parseFloat(amountUsd)
            },
        ],
        isLowerTierThanCurrentAddon: [
            (s, p) => [p.product, s.currentPlatformAddon, s.platformAddons],
            (product, currentPlatformAddon, platformAddons): boolean => {
                if (!currentPlatformAddon || platformAddons.length === 0) {
                    return false
                }
                const currentIdx = platformAddons.findIndex((a) => a.type === currentPlatformAddon.type)
                const targetIdx = platformAddons.findIndex((a) => a.type === product.type)
                if (currentIdx < 0 || targetIdx < 0) {
                    return false
                }
                return targetIdx < currentIdx
            },
        ],
        isSubscribedToAnotherAddon: [
            (s, p) => [s.billing, p.product],
            (billing: BillingType, addon: BillingProductV2AddonType) => {
                const subscribed = addon.subscribed
                if (subscribed) {
                    // They are subscribed to this addon so can't be subscribed to another one
                    return false
                }

                const parentProduct = billing?.products.find((product: any) =>
                    product.addons.find((a: BillingProductV2AddonType) => a.type === addon.type)
                )
                if (!parentProduct) {
                    return false
                }

                if (parentProduct?.type !== 'platform_and_support') {
                    // Only platform and support can have multiple add-ons
                    return false
                }

                return parentProduct.addons.some((a: BillingProductV2AddonType) => a.subscribed)
            },
        ],
        customLimitUsd: [
            (s, p) => [s.billing, p.product],
            (billing, product) => {
                const customLimit = billing?.custom_limits_usd?.[product.type]
                if (customLimit === 0 || customLimit) {
                    return Number(customLimit)
                }
                const usageKeyLimit = product.usage_key ? billing?.custom_limits_usd?.[product.usage_key] : null
                return usageKeyLimit ? Number(usageKeyLimit) : null
            },
        ],
        visibleAddons: [
            (s, p) => [s.featureFlags, p.product],
            (featureFlags: Record<string, any>, product: BillingProductV2Type) => {
                if (!product.addons?.length) {
                    return []
                }

                return product.addons.filter((addon: BillingProductV2AddonType) =>
                    isAddonVisible(product, addon, featureFlags)
                )
            },
        ],
        hasCustomLimitSet: [
            (s) => [s.customLimitUsd],
            (customLimitUsd) => (!!customLimitUsd || customLimitUsd === 0) && customLimitUsd >= 0,
        ],
        isDataPipelinesDeprecated: [
            (_s, p) => [p.product],
            (product: BillingProductV2Type | BillingProductV2AddonType): boolean => {
                return product.type === 'data_pipelines' && dayjs().isAfter(dayjs(DATA_PIPELINES_CUTOFF_DATE))
            },
        ],
        currentAndUpgradePlans: [
            (_s, p) => [p.product],
            (product) => {
                const currentPlanIndex = product.plans.findIndex((plan: BillingPlanType) => plan.current_plan)
                const currentPlan = currentPlanIndex >= 0 ? product.plans?.[currentPlanIndex] : null
                const upgradePlan =
                    // If in debug mode and with no license there will be
                    // no currentPlan. So we want to upgrade to the highest plan.
                    values.isUnlicensedDebug
                        ? product.plans?.[product.plans.length - 1]
                        : product.plans?.[currentPlanIndex + 1]
                return { currentPlan, upgradePlan }
            },
        ],
        freeTier: [(_s, p) => [p.product], (product) => calculateFreeTier(product)],
        billingLimitAsUsage: [
            (_, p) => [p.product],
            (product) => {
                return product.usage_limit || 0
            },
        ],
        billingLimitNextPeriod: [
            (s, p) => [s.billing, p.product],
            (billing, product) => {
                const nextPeriodLimit = billing?.next_period_custom_limits_usd?.[product.type]
                if (nextPeriodLimit === 0 || nextPeriodLimit) {
                    return nextPeriodLimit
                }
                return product.usage_key ? (billing?.next_period_custom_limits_usd?.[product.usage_key] ?? null) : null
            },
        ],
        billingGaugeItems: [
            (s, p) => [p.product, s.billing, s.billingLimitAsUsage],
            (product, billing, billingLimitAsUsage): BillingGaugeItemType[] => {
                return createGaugeItems(product, {
                    billing,
                    billingLimitAsUsage,
                })
            },
        ],
        isAddonProduct: [
            (s, p) => [s.billing, p.product],
            (billing, product): boolean =>
                !!billing?.products?.some((p) => p.addons?.some((addon) => addon.type === product?.type)),
        ],
        unsubscribeReasonQuestions: [
            (s) => [s.surveyResponse],
            (surveyResponse): string => {
                return surveyResponse['$survey_response_2']
                    .map((reason) => {
                        const reasonObject = UNSUBSCRIBE_REASONS.find((r) => r.reason === reason)
                        return reasonObject?.question
                    })
                    .join('\n')
            },
        ],
        trialCancelReasonQuestions: [
            (s) => [s.surveyResponse],
            (surveyResponse): string => {
                return surveyResponse['$survey_response_2']
                    .map((reason) => {
                        const reasonObject = TRIAL_CANCEL_REASONS.find((r) => r.reason === reason)
                        return reasonObject?.question
                    })
                    .join('\n')
            },
        ],
        isProductWithVariants: [
            (_s, p) => [p.product],
            (product): boolean =>
                isProductVariantPrimary(product.type) && 'addons' in product && product.addons?.length > 0,
        ],
        projectedAmountExcludingAddons: [
            (s, p) => [s.isProductWithVariants, p.product],
            (isProductWithVariants, product): string => {
                if (!isProductWithVariants) {
                    return product.projected_amount_usd || '0'
                }

                const mainProduct = product as BillingProductV2Type
                const totalProjected = parseFloat(mainProduct.projected_amount_usd || '0')

                if (!mainProduct.addons?.length) {
                    return totalProjected.toFixed(2)
                }

                const addonProjected = mainProduct.addons.reduce(
                    (sum: number, addon: BillingProductV2AddonType) =>
                        sum + parseFloat(addon.projected_amount_usd || '0'),
                    0
                )

                return Math.max(0, totalProjected - addonProjected).toFixed(2)
            },
        ],
        productVariants: [
            (s, p) => [s.isProductWithVariants, p.product],
            (
                isProductWithVariants: boolean,
                product: BillingProductV2Type
            ): Array<{
                key: string
                product: BillingProductV2Type | BillingProductV2AddonType
                displayName: string
            }> | null => {
                if (!isProductWithVariants) {
                    return null
                }

                const displayNameOverrides: Record<string, string> = {
                    session_replay: 'Web session replay',
                }

                const mainProduct = product as BillingProductV2Type
                const variants: Array<{
                    key: string
                    product: BillingProductV2Type | BillingProductV2AddonType
                    displayName: string
                }> = [
                    {
                        key: mainProduct.type,
                        product: mainProduct as BillingProductV2Type | BillingProductV2AddonType,
                        displayName: displayNameOverrides[mainProduct.type] || mainProduct.name,
                    },
                ]

                mainProduct.addons?.forEach((addon) => {
                    variants.push({
                        key: addon.type,
                        product: addon as BillingProductV2Type | BillingProductV2AddonType,
                        displayName: displayNameOverrides[addon.type] || addon.name,
                    })
                })

                return variants
            },
        ],
        combinedMonetaryData: [
            (s, p) => [s.customLimitUsd, p.product, s.billing],
            (limit: number | null, product: BillingProductV2Type, billing: BillingType | null) => {
                const mainProduct = product as BillingProductV2Type
                const discountPercent = billing?.discount_percent || 0
                const discountMultiplier = 1 - discountPercent / 100

                return {
                    currentTotal: parseFloat(mainProduct.current_amount_usd || '0') * discountMultiplier,
                    projectedTotal: parseFloat(mainProduct.projected_amount_usd_with_limit || '0') * discountMultiplier,
                    billingLimit: limit,
                    discountPercent,
                    rawCurrentTotal: mainProduct.current_amount_usd || '0',
                    rawProjectedTotal: mainProduct.projected_amount_usd_with_limit || '0',
                }
            },
        ],
        combinedMonetaryGaugeItems: [
            (s) => [s.combinedMonetaryData],
            (monetaryData: {
                currentTotal: number
                projectedTotal: number
                billingLimit?: number | null
            }): BillingGaugeItemType[] => {
                const { currentTotal, projectedTotal, billingLimit } = monetaryData

                return [
                    billingLimit && {
                        type: BillingGaugeItemKind.BillingLimit,
                        text: 'Billing limit',
                        value: parseFloat(billingLimit.toFixed(2)),
                        prefix: '$',
                    },
                    {
                        type: BillingGaugeItemKind.ProjectedUsage,
                        text: 'Projected',
                        value: parseFloat(projectedTotal.toFixed(2)),
                        prefix: '$',
                    },
                    {
                        type: BillingGaugeItemKind.CurrentUsage,
                        text: 'Current',
                        value: parseFloat(currentTotal.toFixed(2)),
                        prefix: '$',
                    },
                ].filter(Boolean) as BillingGaugeItemType[]
            },
        ],
        currentAmountTotalActual: [
            (s, p) => [s.isProductWithVariants, p.product, s.visibleAddons],
            (isProductWithVariants, product, visibleAddons): string => {
                if (!product.tiers) {
                    return '0.00'
                }

                // Calculate base product total from tiers
                const productTotal = product.tiers.reduce(
                    (sum, tier) => sum + parseFloat(tier.current_amount_usd || '0'),
                    0
                )

                // For variants, return just the product total (addons shown separately)
                if (isProductWithVariants) {
                    return productTotal.toFixed(2)
                }

                // For non-variants, include addon totals
                const addonTotal =
                    visibleAddons?.reduce(
                        (addonSum, addon) =>
                            addonSum +
                            (addon.tiers?.reduce(
                                (tierSum, tier) => tierSum + parseFloat(tier.current_amount_usd || '0'),
                                0
                            ) || 0),
                        0
                    ) || 0

                return (productTotal + addonTotal).toFixed(2)
            },
        ],
    })),
    listeners(({ actions, values, props }) => ({
        updateBillingLimitsSuccess: () => {
            actions.billingLoaded()
        },
        billingLoaded: () => {
            function calculateDefaultBillingLimit(product: BillingProductV2Type | BillingProductV2AddonType): number {
                const projectedAmount = parseInt(product.projected_amount_usd || '0')
                return product.tiers && projectedAmount ? projectedAmount * 1.5 : DEFAULT_BILLING_LIMIT
            }
            actions.setIsEditingBillingLimit(false)
            actions.setBillingLimitInput(
                values.hasCustomLimitSet ? values.customLimitUsd : calculateDefaultBillingLimit(props.product)
            )
        },
        reportSurveyShown: ({ surveyID }) => {
            posthog.capture(SurveyEventName.SHOWN, {
                $survey_id: surveyID,
            })
            actions.setSurveyID(surveyID)
        },
        reportSurveySent: ({ surveyID, surveyResponse }) => {
            // @note(zach): this is submitting to https://us.posthog.com/project/2/surveys/018b6e13-590c-0000-decb-c727a2b3f462?edit=true
            // $survey_response: open text response
            // $survey_response_1: this is the product type
            // $survey_response_2: list of reasons
            // The order is due to the form being built before reasons we're supported. Please do not change the order.
            posthog.capture(SurveyEventName.SENT, {
                $survey_id: surveyID,
                ...surveyResponse,
            })
            actions.setSurveyID('')
        },
        reportSurveyDismissed: ({ surveyID }) => {
            posthog.capture(SurveyEventName.DISMISSED, {
                $survey_id: surveyID,
            })
            actions.setSurveyID('')
        },
        deactivateProductSuccess: async (_, breakpoint) => {
            if (!values.unsubscribeError && values.surveyID) {
                actions.reportSurveySent(values.surveyID, values.surveyResponse)
                await breakpoint(400)
                document.getElementsByClassName('Navigation3000__scene')[0].scrollIntoView()
            }
        },
        setScrollToProductKey: ({ scrollToProductKey }) => {
            // Only scroll to the product if it's an addon product. With subscribe to all products we don't need it for parent products.
            if (scrollToProductKey && values.isAddonProduct && scrollToProductKey === props.product.type) {
                setTimeout(() => {
                    if (props.productRef?.current) {
                        props.productRef?.current.scrollIntoView({
                            behavior: 'smooth',
                            block: 'center',
                        })
                    }
                }, 0)
            }
        },
        initiateProductUpgrade: ({ plan, product, redirectPath }) => {
            actions.setBillingProductLoading(product.type)
            const products = `${product.type}:${plan?.plan_key}`
            actions.handleProductUpgrade(products, redirectPath)
        },
        handleProductUpgrade: ({ products, redirectPath }) => {
            window.location.href = `/api/billing/activate?products=${products}${
                redirectPath && `&redirect_path=${redirectPath}`
            }`
        },
        confirmProductUpgrade: () => {
            const upgradePlan = values.currentAndUpgradePlans.upgradePlan
            const currentPlatformAddon = values.currentPlatformAddon
            if (!upgradePlan || !currentPlatformAddon) {
                return
            }
            const currentPlanKey =
                currentPlatformAddon.plans?.find((p) => p.current_plan)?.plan_key ||
                currentPlatformAddon.plans?.[0]?.plan_key
            actions.switchFlatrateSubscriptionPlan({
                from_product_key: String(currentPlatformAddon.type),
                from_plan_key: String(currentPlanKey),
                to_product_key: props.product.type,
                to_plan_key: String(upgradePlan.plan_key),
            })
        },
        confirmProductDowngrade: () => {
            const targetPlan = values.currentAndUpgradePlans.upgradePlan
            const currentPlatformAddon = values.currentPlatformAddon
            if (!targetPlan || !currentPlatformAddon) {
                return
            }
            const currentPlanKey =
                currentPlatformAddon.plans?.find((p) => p.current_plan)?.plan_key ||
                currentPlatformAddon.plans?.[0]?.plan_key
            actions.switchFlatrateSubscriptionPlan({
                from_product_key: String(currentPlatformAddon.type),
                from_plan_key: String(currentPlanKey),
                to_product_key: props.product.type,
                to_plan_key: String(targetPlan.plan_key),
            })
        },
        setSwitchPlanLoading: ({ productKey }) => {
            if (productKey === null) {
                if (values.confirmUpgradeModalOpen) {
                    actions.hideConfirmUpgradeModal()
                }
                if (values.confirmDowngradeModalOpen) {
                    actions.hideConfirmDowngradeModal()
                }
            }
        },
        activateTrial: async (_, breakpoint) => {
            actions.setTrialLoading(true)
            try {
                await api.create(`api/billing/trials/activate`, {
                    type: 'autosubscribe',
                    target: props.product.type,
                })
                lemonToast.success('Your trial has been activated!')
                await breakpoint(400)
                window.location.reload()
            } catch {
                lemonToast.error('There was an error activating your trial. Please try again or contact support.')
                actions.setTrialLoading(false)
                actions.loadBilling()
            }
        },
        cancelTrial: async (_, breakpoint) => {
            actions.setTrialLoading(true)
            try {
                await api.create(`api/billing/trials/cancel`)
                lemonToast.success('Your trial has been cancelled!')
                if (values.surveyID) {
                    actions.reportSurveySent(values.surveyID, values.surveyResponse)
                }
                await breakpoint(1000)
                window.location.reload()
            } catch {
                lemonToast.error('There was an error cancelling your trial. Please try again or contact support.')
                actions.setTrialLoading(false)
                actions.loadBilling()
            }
        },
        triggerMoreHedgehogs: async (_, breakpoint) => {
            for (let i = 0; i < 5; i++) {
                props.hogfettiTrigger?.()
                await breakpoint(200)
            }
        },
        removeBillingLimitNextPeriod: async ({ productType }) => {
            try {
                await api.update('api/billing', { reset_limit_next_period: productType })
                lemonToast.success('Billing limit for next period has been removed.')
            } catch (e) {
                console.error(e)
                lemonToast.error(
                    'There was an error removing your billing limit for next period. Please try again or contact support.'
                )
            } finally {
                actions.loadBilling()
            }
        },
    })),
    forms(({ actions, props }) => ({
        billingLimitInput: {
            errors: ({ input }) => ({
                input:
                    input === null || Number.isInteger(input)
                        ? input > 25000
                            ? 'Please enter a number less than 25,000'
                            : undefined
                        : 'Please enter a whole number',
            }),
            submit: async ({ input }) => {
                if (props.product.current_amount_usd && input < props.product.current_amount_usd) {
                    LemonDialog.open({
                        maxWidth: '600px',
                        title: 'Billing limit warning',
                        description:
                            "The billing limit you set is below your current usage. If you proceed, your current period's limit will be set to your current usage (to prevent additional charges), and the new lower limit will go into effect in your next billing period. Are you sure you want to proceed?",
                        primaryButton: {
                            status: 'danger',
                            children: 'Yes, I understand',
                            onClick: () =>
                                actions.updateBillingLimits({
                                    [props.product.type]: input,
                                }),
                        },
                        secondaryButton: {
                            children: 'No, I changed my mind',
                        },
                    })
                    return
                }

                if (props.product.projected_amount_usd && input < props.product.projected_amount_usd) {
                    LemonDialog.open({
                        maxWidth: '600px',
                        title: 'Billing limit warning',
                        description:
                            'Your predicted usage is above your billing limit which is likely to result in usage being throttled and data being dropped. Are you sure you want to proceed?',
                        primaryButton: {
                            status: 'danger',
                            children: 'Yes, I understand',
                            onClick: () =>
                                actions.updateBillingLimits({
                                    [props.product.type]: input,
                                }),
                        },
                        secondaryButton: {
                            children: 'No, I changed my mind',
                        },
                    })
                    return
                }
                actions.updateBillingLimits({
                    [props.product.type]: input,
                })
            },
            options: {
                alwaysShowErrors: true,
            },
        },
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            actions.setScrollToProductKey(values.scrollToProductKey)
            actions.billingLoaded()
        },
    })),
])
