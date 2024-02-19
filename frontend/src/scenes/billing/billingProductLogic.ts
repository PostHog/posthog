import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'
import React from 'react'

import { BillingProductV2AddonType, BillingProductV2Type, BillingV2PlanType, BillingV2TierType } from '~/types'

import { convertAmountToUsage } from './billing-utils'
import { billingLogic } from './billingLogic'
import type { billingProductLogicType } from './billingProductLogicType'
import { BillingGaugeItemKind, BillingGaugeItemType } from './types'

const DEFAULT_BILLING_LIMIT = 500

export interface BillingProductLogicProps {
    product: BillingProductV2Type | BillingProductV2AddonType
    billingLimitInputRef?: React.MutableRefObject<HTMLInputElement | null>
}

export const billingProductLogic = kea<billingProductLogicType>([
    props({} as BillingProductLogicProps),
    key((props) => props.product.type),
    path(['scenes', 'billing', 'billingProductLogic']),
    connect({
        values: [billingLogic, ['billing', 'isUnlicensedDebug', 'scrollToProductKey']],
        actions: [
            billingLogic,
            [
                'loadBillingSuccess',
                'updateBillingLimitsSuccess',
                'deactivateProduct',
                'setProductSpecificAlert',
                'setScrollToProductKey',
            ],
        ],
    }),
    actions({
        setIsEditingBillingLimit: (isEditingBillingLimit: boolean) => ({ isEditingBillingLimit }),
        setBillingLimitInput: (billingLimitInput: number | undefined) => ({ billingLimitInput }),
        billingLoaded: true,
        setShowTierBreakdown: (showTierBreakdown: boolean) => ({ showTierBreakdown }),
        toggleIsPricingModalOpen: true,
        toggleIsPlanComparisonModalOpen: true,
        setSurveyResponse: (surveyResponse: string, key: string) => ({ surveyResponse, key }),
        reportSurveyShown: (surveyID: string, productType: string) => ({ surveyID, productType }),
        reportSurveySent: (surveyID: string, surveyResponse: Record<string, string>) => ({
            surveyID,
            surveyResponse,
        }),
        reportSurveyDismissed: (surveyID: string) => ({ surveyID }),
        setSurveyID: (surveyID: string) => ({ surveyID }),
    }),
    reducers({
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
        billingLimitInput: [
            DEFAULT_BILLING_LIMIT as number | undefined,
            {
                setBillingLimitInput: (_, { billingLimitInput }) => billingLimitInput,
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
                const currentPlan = product.plans?.[currentPlanIndex]
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
        showBillingLimitInput: [
            (s) => [s.billing, s.customLimitUsd, s.isEditingBillingLimit],
            (billing, customLimitUsd, isEditingBillingLimit) => {
                return billing?.billing_period?.interval == 'month' && (customLimitUsd || isEditingBillingLimit)
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
                        ? convertAmountToUsage(`${billingLimitInput}`, productAndAddonTiers, billing?.discount_percent)
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
        loadBillingSuccess: actions.billingLoaded,
        updateBillingLimitsSuccess: actions.billingLoaded,
        billingLoaded: () => {
            actions.setIsEditingBillingLimit(false)
            actions.setBillingLimitInput(
                parseInt(values.customLimitUsd || '0') ||
                    (props.product.tiers ? parseInt(props.product.projected_amount_usd || '0') * 1.5 : 0) ||
                    DEFAULT_BILLING_LIMIT
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
                }
            }
        },
    })),
    events(({ actions, values }) => ({
        afterMount: () => {
            actions.setScrollToProductKey(values.scrollToProductKey)
        },
    })),
])
