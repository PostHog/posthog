import { LemonDialog, lemonToast } from '@posthog/lemon-ui'
import { actions, connect, events, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import posthog from 'posthog-js'
import React from 'react'

import { BillingPlanType, BillingProductV2AddonType, BillingProductV2Type, BillingTierType } from '~/types'

import { convertAmountToUsage } from './billing-utils'
import { billingLogic } from './billingLogic'
import type { billingProductLogicType } from './billingProductLogicType'
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
    { reason: 'Other (let us know below!)', question: 'Why are you leaving?' },
]

export const randomizeReasons = (reasons: UnsubscribeReason[]): UnsubscribeReason[] => {
    const shuffledReasons = reasons.slice(0, -1).sort(() => Math.random() - 0.5)
    shuffledReasons.push(reasons[reasons.length - 1])
    return shuffledReasons
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
    connect({
        values: [
            billingLogic,
            ['billing', 'isUnlicensedDebug', 'scrollToProductKey', 'unsubscribeError'],
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
            ],
        ],
    }),
    actions({
        setIsEditingBillingLimit: (isEditingBillingLimit: boolean) => ({ isEditingBillingLimit }),
        setBillingLimitInput: (billingLimitInput: number | null) => ({ billingLimitInput }),
        billingLoaded: true,
        setShowTierBreakdown: (showTierBreakdown: boolean) => ({ showTierBreakdown }),
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
        setTrialModalOpen: (isOpen: boolean) => ({ isOpen }),
        setTrialLoading: (loading: boolean) => ({ loading }),
        setUnsubscribeModalStep: (step: number) => ({ step }),
        resetUnsubscribeModalStep: true,
        setHedgehogSatisfied: (satisfied: boolean) => ({ satisfied }),
        triggerMoreHedgehogs: true,
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
        trialModalOpen: [
            false,
            {
                setTrialModalOpen: (_, { isOpen }) => isOpen,
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
    }),
    selectors(({ values }) => ({
        customLimitUsd: [
            (s, p) => [s.billing, p.product],
            (billing, product) => {
                const customLimit = billing?.custom_limits_usd?.[product.type]
                if (customLimit === 0 || customLimit) {
                    return customLimit
                }
                return product.usage_key ? billing?.custom_limits_usd?.[product.usage_key] ?? null : null
            },
        ],
        hasCustomLimitSet: [
            (s) => [s.customLimitUsd],
            (customLimitUsd) => (!!customLimitUsd || customLimitUsd === 0) && customLimitUsd >= 0,
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
                const productAndAddonTiers: BillingTierType[][] = [product.tiers, ...addonTiers].filter(
                    Boolean
                ) as BillingTierType[][]
                return product.tiers
                    ? isEditingBillingLimit
                        ? convertAmountToUsage(
                              `${billingLimitInput.input}`,
                              productAndAddonTiers,
                              billing?.discount_percent
                          )
                        : convertAmountToUsage(
                              customLimitUsd ? `${customLimitUsd}` : '',
                              productAndAddonTiers,
                              billing?.discount_percent
                          )
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
                    .join(' ')
                    .concat(' (required)')
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
            posthog.capture('survey shown', {
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
        activateTrial: async (_, breakpoint) => {
            actions.setTrialLoading(true)
            try {
                await api.create(`api/billing/trials/activate`, {
                    type: 'autosubscribe',
                    target: props.product.type,
                })
                lemonToast.success('Your trial has been activated!')
            } catch (e) {
                lemonToast.error('There was an error activating your trial. Please try again or contact support.')
            } finally {
                await breakpoint(400)
                window.location.reload()
                actions.setTrialLoading(false)
                actions.setTrialModalOpen(false)
            }
        },
        cancelTrial: async () => {
            actions.setTrialLoading(true)
            try {
                await api.create(`api/billing/trials/cancel`)
                lemonToast.success('Your trial has been cancelled!')
            } catch (e) {
                console.error(e)
                lemonToast.error('There was an error cancelling your trial. Please try again or contact support.')
            } finally {
                actions.loadBilling()
                window.location.reload()
                actions.setTrialLoading(false)
            }
        },
        triggerMoreHedgehogs: async (_, breakpoint) => {
            for (let i = 0; i < 5; i++) {
                props.hogfettiTrigger?.()
                await breakpoint(200)
            }
        },
    })),
    forms(({ actions, props, values }) => ({
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
                const addonTiers =
                    'addons' in props.product
                        ? props.product.addons
                              ?.filter((addon: BillingProductV2AddonType) => addon.subscribed)
                              ?.map((addon: BillingProductV2AddonType) => addon.tiers)
                        : []

                const productAndAddonTiers: BillingTierType[][] = [props.product.tiers, ...addonTiers].filter(
                    Boolean
                ) as BillingTierType[][]

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
                                    [props.product.type]: input,
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
                                    [props.product.type]: input,
                                }),
                        },
                        secondaryButton: {
                            children: 'I changed my mind',
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
