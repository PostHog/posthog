import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { BillingProductV2Type } from '~/types'
import { billingLogic } from '../billingLogic'
import type { billingProductLogicType } from './billingProductLogicType'
import { convertUsageToAmount, convertAmountToUsage } from '../billing-utils'

const DEFAULT_BILLING_LIMIT = 500

export const billingProductLogic = kea<billingProductLogicType>([
    key((props) => props.product.type),
    path(['scenes', 'billing', 'billingProductLogic']),
    connect({
        values: [billingLogic, ['billing']],
        actions: [billingLogic, ['loadBillingSuccess', 'updateBillingLimitsSuccess']],
    }),
    props({
        product: {} as BillingProductV2Type,
    }),
    actions({
        setIsEditingBillingLimit: (isEditingBillingLimit: boolean) => ({ isEditingBillingLimit }),
        setBillingLimitInput: (billingLimitInput: number | undefined) => ({ billingLimitInput }),
        billingLoaded: true,
        setShowTierBreakdown: (showTierBreakdown: boolean) => ({ showTierBreakdown }),
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
    }),
    selectors({
        customLimitUsd: [
            (s, p) => [s.billing, p.product],
            (billing, product) => {
                return billing?.custom_limits_usd?.[product.type]
            },
        ],
        showBillingLimitInput: [
            (s) => [s.billing, s.customLimitUsd, s.isEditingBillingLimit],
            (billing, customLimitUsd, isEditingBillingLimit) => {
                return billing?.billing_period?.interval == 'month' && (customLimitUsd || isEditingBillingLimit)
            },
        ],
        freeTier: [
            (s, p) => [s.billing, p.product],
            (billing, product) => {
                return (billing?.has_active_subscription ? product.tiers?.[0]?.up_to : product.free_allocation) || 0
            },
        ],
        billingLimitAsUsage: [
            (s, p) => [p.product, s.isEditingBillingLimit, s.billingLimitInput, s.customLimitUsd],
            (product, isEditingBillingLimit, billingLimitInput, customLimitUsd) => {
                return product.tiers
                    ? isEditingBillingLimit
                        ? convertAmountToUsage(`${billingLimitInput}`, product.tiers)
                        : convertAmountToUsage(customLimitUsd || '', product.tiers)
                    : 0
            },
        ],
        billingGaugeItems: [
            (s, p) => [p.product, s.freeTier, s.billingLimitAsUsage],
            (product, freeTier, billingLimitAsUsage) => {
                return [
                    {
                        text: 'Free tier limit',
                        color: 'success-light',
                        value: freeTier,
                        top: true,
                    },
                    {
                        text: 'Current',
                        color: product.percentage_usage <= 1 ? 'success' : 'danger',
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
                    (props.product.tiers
                        ? parseInt(
                              convertUsageToAmount((props.product.projected_usage || 0) * 1.5, props.product.tiers)
                          )
                        : 0) ||
                    DEFAULT_BILLING_LIMIT
            )
        },
    })),
])
