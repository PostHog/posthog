import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { BillingProductV2AddonType, BillingProductV2Type } from '~/types'
import { billingLogic } from '../billingLogic'
import type { billingProductLogicType } from './billingProductLogicType'
import { convertAmountToUsage } from '../billing-utils'

const DEFAULT_BILLING_LIMIT = 500

export const billingProductLogic = kea<billingProductLogicType>([
    key((props) => props.product.type),
    path(['scenes', 'billing', 'billingProductLogic']),
    connect({
        values: [billingLogic, ['billing']],
        actions: [billingLogic, ['loadBillingSuccess', 'updateBillingLimitsSuccess']],
    }),
    props({
        product: {} as BillingProductV2Type | BillingProductV2AddonType,
    }),
    actions({
        setIsEditingBillingLimit: (isEditingBillingLimit: boolean) => ({ isEditingBillingLimit }),
        setBillingLimitInput: (billingLimitInput: number | undefined) => ({ billingLimitInput }),
        billingLoaded: true,
        setShowTierBreakdown: (showTierBreakdown: boolean) => ({ showTierBreakdown }),
        toggleIsPricingModalOpen: true,
        toggleIsPlanComparisonModalOpen: true,
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
    }),
    selectors({
        customLimitUsd: [
            (s, p) => [s.billing, p.product],
            (billing, product) => {
                return billing?.custom_limits_usd?.[product.type] || billing?.custom_limits_usd?.[product.usage_key]
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
                return product.tiers
                    ? isEditingBillingLimit
                        ? convertAmountToUsage(`${billingLimitInput}`, product.tiers, billing?.discount_percent)
                        : convertAmountToUsage(customLimitUsd || '', product.tiers, billing?.discount_percent)
                    : 0
            },
        ],
        billingGaugeItems: [
            (s, p) => [p.product, s.freeTier, s.billingLimitAsUsage],
            (product, freeTier, billingLimitAsUsage) => {
                return [
                    freeTier
                        ? {
                              text: 'Free tier limit',
                              color: 'success-light',
                              value: freeTier,
                              top: true,
                          }
                        : undefined,
                    {
                        text: 'Current',
                        color: product.percentage_usage && product.percentage_usage <= 1 ? 'success' : 'danger',
                        value: product.current_usage || 0,
                        top: false,
                    },
                    product.projected_usage && product.projected_usage > (product.current_usage || 0)
                        ? {
                              text: 'Projected',
                              color: 'border',
                              value: product.projected_usage || 0,
                              top: false,
                          }
                        : undefined,
                    billingLimitAsUsage
                        ? {
                              text: 'Billing limit',
                              color: 'primary-alt-light',
                              top: true,
                              value: billingLimitAsUsage || 0,
                          }
                        : (undefined as any),
                ].filter(Boolean)
            },
        ],
    }),
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
    })),
])
