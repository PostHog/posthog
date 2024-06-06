import { LemonDialog } from '@posthog/lemon-ui'
import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import posthog from 'posthog-js'
import React from 'react'

import { BillingProductV2AddonType, BillingProductV2Type, BillingV2PlanType, BillingV2TierType } from '~/types'

import { convertAmountToUsage } from './billing-utils'
import { billingLogic } from './billingLogic'
import type { billingProductLogicType } from './billingProductLogicType'
import { BillingGaugeItemKind, BillingGaugeItemType } from './types'

const DEFAULT_BILLING_LIMIT: number = 500

export interface BillingProductLogicProps {
    product: BillingProductV2Type | BillingProductV2AddonType
    productRef?: React.MutableRefObject<HTMLDivElement | null>
    billingLimitInputRef?: React.MutableRefObject<HTMLInputElement | null>
}

export const billingProductLogic = kea<billingProductLogicType>([
    props({} as BillingProductLogicProps),
    key((props) => props.product.type),
    path(['scenes', 'billing', 'billingProductLogic']),
    connect({
        values: [billingLogic, ['billing', 'isUnlicensedDebug', 'scrollToProductKey', 'unsubscribeError']],
        actions: [
            billingLogic,
            [
                'updateBillingLimits',
                'updateBillingLimitsSuccess',
                'loadBillingSuccess',
                'deactivateProduct',
                'setProductSpecificAlert',
                'setScrollToProductKey',
                'deactivateProductSuccess',
            ],
        ],
    }),
    actions({
        setIsEditingBillingLimit: (isEditingBillingLimit: boolean) => ({ isEditingBillingLimit }),
        setBillingLimitInput: (billingLimitInput: number | undefined) => ({ billingLimitInput }),
        billingLoaded: true,
        setShowTierBreakdown: (showTierBreakdown: boolean) => ({ showTierBreakdown }),
        toggleIsPricingModalOpen: true,
        toggleIsPlanComparisonModalOpen: (highlightedFeatureKey?: string) => ({ highlightedFeatureKey }),
        setSurveyResponse: (surveyResponse: string, key: string) => ({ surveyResponse, key }),
        reportSurveyShown: (surveyID: string, productType: string) => ({ surveyID, productType }),
        reportSurveySent: (surveyID: string, surveyResponse: Record<string, string>) => ({
            surveyID,
            surveyResponse,
        }),
        reportSurveyDismissed: (surveyID: string) => ({ surveyID }),
        setSurveyID: (surveyID: string) => ({ surveyID }),
        setBillingProductLoading: (productKey: string | null) => ({ productKey }),
        initiateProductUpgrade: (
            product: BillingProductV2Type | BillingProductV2AddonType,
            plan: BillingV2PlanType,
            redirectPath?: string
        ) => ({
            plan,
            product,
            redirectPath,
        }),
        handleProductUpgrade: (
            product: BillingProductV2Type | BillingProductV2AddonType,
            plan: BillingV2PlanType,
            redirectPath?: string
        ) => ({
            plan,
            product,
            redirectPath,
        }),
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
            {},
            {
                setSurveyResponse: (state, { surveyResponse, key }) => {
                    return { ...state, [key]: surveyResponse }
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
    }),
    selectors(({ values }) => ({
        customLimitUsd: [
            (s, p) => [s.billing, p.product],
            (billing, product) => {
                return (
                    billing?.custom_limits_usd?.[product.type] ||
                    (product.usage_key ? billing?.custom_limits_usd?.[product.usage_key] : '')
                )
            },
        ],
        currentAndUpgradePlans: [
            (_s, p) => [p.product],
            (product) => {
                const currentPlanIndex = product.plans.findIndex((plan: BillingV2PlanType) => plan.current_plan)
                const currentPlan = currentPlanIndex >= 0 ? product.plans?.[currentPlanIndex] : null
                const upgradePlan =
                    // If in debug mode and with no license there will be
                    // no currentPlan. So we want to upgrade to the highest plan.
                    values.isUnlicensedDebug
                        ? product.plans?.[product.plans.length - 1]
                        : product.plans?.[currentPlanIndex + 1]
                const downgradePlan = product.plans?.[currentPlanIndex - 1]
                return { currentPlan, upgradePlan, downgradePlan }
            },
        ],
        freeTier: [
            (_s, p) => [p.product],
            (product) => {
                return (
                    (product.subscribed && product.tiered
                        ? product.tiers?.[0]?.unit_amount_usd === '0'
                            ? product.tiers?.[0]?.up_to
                            : 0
                        : product.free_allocation) || 0
                )
            },
        ],
        billingLimitAsUsage: [
            (s, p) => [s.billing, p.product, s.isEditingBillingLimit, s.billingLimitInput, s.customLimitUsd],
            (billing, product, isEditingBillingLimit, billingLimitInput, customLimitUsd) => {
                // cast the product as a product, not an addon, to avoid TS errors. This is fine since we're just getting the tiers.
                product = product as BillingProductV2Type
                const addonTiers = product.addons
                    ?.filter((addon: BillingProductV2AddonType) => addon.subscribed)
                    ?.map((addon: BillingProductV2AddonType) => addon.tiers)
                const productAndAddonTiers: BillingV2TierType[][] = [product.tiers, ...addonTiers].filter(
                    Boolean
                ) as BillingV2TierType[][]
                return product.tiers
                    ? isEditingBillingLimit
                        ? convertAmountToUsage(
                              `${billingLimitInput.input}`,
                              productAndAddonTiers,
                              billing?.discount_percent
                          )
                        : convertAmountToUsage(customLimitUsd || '', productAndAddonTiers, billing?.discount_percent)
                    : 0
            },
        ],
        billingGaugeItems: [
            (s, p) => [p.product, s.billing, s.freeTier, s.billingLimitAsUsage],
            (product, billing, freeTier, billingLimitAsUsage): BillingGaugeItemType[] => {
                return [
                    billingLimitAsUsage && billing?.discount_percent !== 100
                        ? {
                              type: BillingGaugeItemKind.BillingLimit,
                              text: 'Billing limit',
                              top: true,
                              value: billingLimitAsUsage || 0,
                          }
                        : (undefined as any),
                    freeTier
                        ? {
                              type: BillingGaugeItemKind.FreeTier,
                              text: 'Free tier limit',
                              value: freeTier,
                              top: true,
                          }
                        : undefined,
                    product.projected_usage && product.projected_usage > (product.current_usage || 0)
                        ? {
                              type: BillingGaugeItemKind.ProjectedUsage,
                              text: 'Projected',
                              value: product.projected_usage || 0,
                              top: false,
                          }
                        : undefined,
                    {
                        type: BillingGaugeItemKind.CurrentUsage,
                        text: 'Current',
                        value: product.current_usage || 0,
                        top: false,
                    },
                ].filter(Boolean)
            },
        ],
    })),
    listeners(({ actions, values, props }) => ({
        updateBillingLimitsSuccess: () => {
            actions.billingLoaded()
        },
        billingLoaded: () => {
            actions.setIsEditingBillingLimit(false)
            actions.setBillingLimitInput(
                values.customLimitUsd
                    ? parseInt(values.customLimitUsd)
                    : props.product.tiers && parseInt(props.product.projected_amount_usd || '0')
                    ? parseInt(props.product.projected_amount_usd || '0') * 1.5
                    : DEFAULT_BILLING_LIMIT
            )
        },
        reportSurveyShown: ({ surveyID }) => {
            posthog.capture('survey shown', {
                $survey_id: surveyID,
            })
            actions.setSurveyID(surveyID)
        },
        reportSurveySent: ({ surveyID, surveyResponse }) => {
            posthog.capture('survey sent', {
                $survey_id: surveyID,
                ...surveyResponse,
            })
            actions.setSurveyID('')
        },
        reportSurveyDismissed: ({ surveyID }) => {
            posthog.capture('survey dismissed', {
                $survey_id: surveyID,
            })
            actions.setSurveyID('')
        },
        deactivateProductSuccess: () => {
            if (!values.unsubscribeError) {
                const textAreaNotEmpty = values.surveyResponse['$survey_response']?.length > 0
                textAreaNotEmpty
                    ? actions.reportSurveySent(values.surveyID, values.surveyResponse)
                    : actions.reportSurveyDismissed(values.surveyID)
            }
        },
        setScrollToProductKey: ({ scrollToProductKey }) => {
            if (scrollToProductKey && scrollToProductKey === props.product.type) {
                const { currentPlan } = values.currentAndUpgradePlans

                if (currentPlan?.initial_billing_limit) {
                    actions.setProductSpecificAlert({
                        status: 'warning',
                        title: 'Billing Limit Automatically Applied',
                        pathName: '/organization/billing',
                        dismissKey: `auto-apply-billing-limit-${props.product.type}`,
                        message: `To protect your costs and ours, we've automatically applied a $${currentPlan?.initial_billing_limit} billing limit for ${props.product.name}.`,
                        action: {
                            onClick: () => {
                                actions.setIsEditingBillingLimit(true)
                                setTimeout(() => {
                                    if (props.billingLimitInputRef?.current) {
                                        props.billingLimitInputRef?.current.focus()
                                        props.billingLimitInputRef?.current.scrollIntoView({
                                            behavior: 'smooth',
                                            block: 'nearest',
                                        })
                                    }
                                }, 0)
                            },
                            children: 'Update billing limit',
                        },
                    })
                } else {
                    setTimeout(() => {
                        if (props.productRef?.current) {
                            props.productRef?.current.scrollIntoView({
                                behavior: 'smooth',
                                block: 'center',
                            })
                            props.productRef?.current.classList.add('border')
                            props.productRef?.current.classList.add('border-primary-3000')
                        }
                    }, 0)
                }
            }
        },
        initiateProductUpgrade: ({ plan, product, redirectPath }) => {
            actions.setBillingProductLoading(product.type)
            actions.handleProductUpgrade(product, plan, redirectPath)
        },
        handleProductUpgrade: ({ plan, product, redirectPath }) => {
            window.location.href = `/api/billing/activation?products=${product.type}:${plan?.plan_key}${
                redirectPath && `&redirect_path=${redirectPath}`
            }`
        },
    })),
    forms(({ actions, props, values }) => ({
        billingLimitInput: {
            errors: ({ input }) => ({
                input: input === undefined || Number.isInteger(input) ? undefined : 'Please enter a whole number',
            }),
            submit: async ({ input }) => {
                const addonTiers =
                    'addons' in props.product
                        ? props.product.addons
                              ?.filter((addon: BillingProductV2AddonType) => addon.subscribed)
                              ?.map((addon: BillingProductV2AddonType) => addon.tiers)
                        : []

                const productAndAddonTiers: BillingV2TierType[][] = [props.product.tiers, ...addonTiers].filter(
                    Boolean
                ) as BillingV2TierType[][]

                const newAmountAsUsage = props.product.tiers
                    ? convertAmountToUsage(`${input}`, productAndAddonTiers, values.billing?.discount_percent)
                    : 0

                if (props.product.current_usage && newAmountAsUsage < props.product.current_usage) {
                    LemonDialog.open({
                        title: 'Billing limit warning',
                        description:
                            'Your new billing limit will be below your current usage. Your bill will not increase for this period but parts of the product will stop working and data may be lost.',
                        primaryButton: {
                            status: 'danger',
                            children: 'I understand',
                            onClick: () =>
                                actions.updateBillingLimits({
                                    [props.product.type]: typeof input === 'number' ? `${input}` : null,
                                }),
                        },
                        secondaryButton: {
                            children: 'I changed my mind',
                        },
                    })
                    return
                }

                if (props.product.projected_usage && newAmountAsUsage < props.product.projected_usage) {
                    LemonDialog.open({
                        title: 'Billing limit warning',
                        description:
                            'Your predicted usage is above your billing limit which is likely to result in usage being throttled.',
                        primaryButton: {
                            children: 'I understand',
                            onClick: () =>
                                actions.updateBillingLimits({
                                    [props.product.type]: typeof input === 'number' ? `${input}` : null,
                                }),
                        },
                        secondaryButton: {
                            children: 'I changed my mind',
                        },
                    })
                    return
                }
                actions.updateBillingLimits({
                    [props.product.type]: typeof input === 'number' ? `${input}` : null,
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
