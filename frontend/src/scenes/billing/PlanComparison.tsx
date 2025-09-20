import './PlanComparison.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import React, { useState } from 'react'
import useResizeObserver from 'use-resize-observer'

import { IconCheckCircle, IconWarning, IconX } from '@posthog/icons'
import { LemonModal, LemonTag, Link } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { getProductIcon } from 'scenes/products/Products'

import { BillingFeatureType, BillingPlanType, BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'
import { convertLargeNumberToWords, getProration } from './billing-utils'
import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'

export function PlanIcon({
    feature,
    className,
    timeDenominator,
}: {
    feature?: BillingFeatureType
    className?: string
    timeDenominator?: string
}): JSX.Element {
    return (
        <div className="flex items-center text-xs text-secondary">
            {!feature ? (
                <>
                    <IconX className={clsx('text-danger mx-4', className)} />
                </>
            ) : feature.limit ? (
                <>
                    <IconWarning className={clsx('text-warning mx-4 shrink-0', className)} />
                    {feature.limit &&
                        `${convertLargeNumberToWords(feature.limit, null)} ${feature.unit && feature.unit}${
                            timeDenominator ? `/${timeDenominator}` : ''
                        }`}
                    {feature.note}
                </>
            ) : (
                <>
                    <IconCheckCircle className={clsx('text-success mx-4 shrink-0', className)} />
                    {feature.note}
                </>
            )}
        </div>
    )
}

const PricingTiers = ({
    plan,
    product,
}: {
    plan: BillingPlanType
    product: BillingProductV2Type | BillingProductV2AddonType
}): JSX.Element => {
    const { width, ref: tiersRef } = useResizeObserver()
    const tiers = plan?.tiers

    const allTierPrices = tiers?.map((tier) => parseFloat(tier.unit_amount_usd))
    const sigFigs = allTierPrices?.map((price) => price?.toString().split('.')[1]?.length).sort((a, b) => b - a)[0]

    return (
        <>
            {tiers ? (
                tiers?.map((tier, i) => (
                    <div
                        key={`${plan.plan_key}-${product.type}-${tier.up_to}`}
                        className={clsx(
                            'flex',
                            width && width < 100 ? 'flex-col mb-2' : 'justify-between items-center'
                        )}
                        ref={tiersRef}
                    >
                        <span className="text-xs">
                            {convertLargeNumberToWords(tier.up_to, tiers[i - 1]?.up_to, true, product.unit)}
                        </span>
                        <span className="font-bold">
                            {i === 0 && parseFloat(tier.unit_amount_usd) === 0
                                ? 'Free'
                                : `$${parseFloat(tier.unit_amount_usd).toFixed(sigFigs)}`}
                        </span>
                    </div>
                ))
            ) : product?.free_allocation ? (
                <div
                    key={`${plan.plan_key}-${product.type}-tiers`}
                    className={clsx('flex', width && width < 100 ? 'flex-col mb-2' : ' justify-between items-center')}
                    ref={tiersRef}
                >
                    <span className="text-xs">
                        Up to {convertLargeNumberToWords(product?.free_allocation, null)} {product?.unit}s/mo
                    </span>
                    <span className="font-bold">Free</span>
                </div>
            ) : null}
        </>
    )
}

export const PlanComparison = ({
    product,
    includeAddons = false,
}: {
    product: BillingProductV2Type
    includeAddons?: boolean
}): JSX.Element | null => {
    const { billing, timeRemainingInSeconds, timeTotalInSeconds } = useValues(billingLogic)
    const { width, ref: planComparisonRef } = useResizeObserver()
    const { surveyID, comparisonModalHighlightedFeatureKey } = useValues(billingProductLogic({ product }))

    const { featureFlags } = useValues(featureFlagLogic)

    const plans = product.plans?.filter(
        (plan) => !plan.included_if || plan.included_if == 'has_subscription' || plan.current_plan
    )
    if (plans?.length === 0) {
        return null
    }
    const fullyFeaturedPlan = plans[plans.length - 1]

    return (
        <table className="PlanComparison w-full table-fixed" ref={planComparisonRef}>
            <thead>
                <tr>
                    <td />
                    {plans?.map((plan) => (
                        <td key={`plan-type-${plan.plan_key}`}>
                            <h3 className="font-bold">{plan.name}</h3>
                        </td>
                    ))}
                </tr>
            </thead>
            <tbody>
                <tr className="PlanTable__tr__border">
                    <td className="font-bold">Monthly {product.tiered && 'base '} price</td>
                    {plans?.map((plan) => {
                        const { prorationAmount, isProrated } = getProration({
                            timeRemainingInSeconds,
                            timeTotalInSeconds,
                            amountUsd: plan.unit_amount_usd,
                            hasActiveSubscription: billing?.has_active_subscription,
                        })
                        return (
                            <td key={`${plan.plan_key}-basePrice`} className="text-sm font-medium">
                                {plan.free_allocation && !plan.tiers
                                    ? 'Free forever'
                                    : plan.unit_amount_usd
                                      ? `$${parseFloat(plan.unit_amount_usd).toFixed(0)} per month`
                                      : plan.contact_support
                                        ? 'Custom'
                                        : plan.included_if == 'has_subscription'
                                          ? billing?.subscription_level === 'custom'
                                              ? 'Free, included with any product subscription'
                                              : 'Usage-based - starting at $0'
                                          : '$0 per month'}
                                {isProrated && (
                                    <p className="text-xxs text-secondary font-normal italic mt-2">
                                        Pay ~${prorationAmount} today{isProrated && ' (prorated)'} and{' '}
                                        {isProrated && `$${parseInt(plan.unit_amount_usd || '0')} `}every month
                                        thereafter.
                                    </p>
                                )}
                            </td>
                        )
                    })}
                </tr>
                {product.tiered && (
                    <tr className="PlanTable__tr__border">
                        <th scope="row">
                            {includeAddons && product.addons?.length > 0 && (
                                <p className="ml-0">
                                    <span className="font-bold">{product.name}</span>
                                </p>
                            )}
                            <p className="ml-0 text-xs mt-1">Priced per {product.unit}</p>
                        </th>
                        {plans?.map((plan) => (
                            <td key={`${plan.plan_key}-tiers-td`}>
                                <PricingTiers plan={plan} product={product} />
                            </td>
                        ))}
                    </tr>
                )}
                {includeAddons && product.addons.length > 0 && (
                    <tr>
                        <th colSpan={1} className="PlanTable__th__section rounded text-left">
                            <h3 className="mt-6 mb-6">Available add-ons:</h3>
                        </th>
                    </tr>
                )}
                {includeAddons &&
                    product.addons
                        ?.filter((addon) => {
                            if (addon.inclusion_only) {
                                if (featureFlags[FEATURE_FLAGS.PERSONLESS_EVENTS_NOT_SUPPORTED]) {
                                    return false
                                }
                            }
                            return true
                        })
                        .map((addon) => {
                            return addon.tiered ? (
                                <tr key={addon.name + 'pricing-row'} className="PlanTable__tr__border">
                                    <th scope="row">
                                        <p className="ml-0">
                                            <Tooltip title={addon.description}>
                                                <span className="font-bold cursor-default">{addon.name}</span>
                                            </Tooltip>
                                            <Tooltip
                                                title={
                                                    addon.inclusion_only
                                                        ? 'Automatically charged based on SDK config options and usage.'
                                                        : 'If subscribed, charged on all usage.'
                                                }
                                            >
                                                <LemonTag
                                                    type={addon.inclusion_only ? 'option' : 'primary'}
                                                    className="ml-2"
                                                >
                                                    {addon.inclusion_only ? 'config' : 'add-on'}
                                                </LemonTag>
                                            </Tooltip>
                                        </p>
                                        <p className="ml-0 text-xs text-secondary mt-1">Priced per {addon.unit}</p>
                                    </th>
                                    {plans?.map((plan, i) => {
                                        // If the parent plan is free, the addon isn't available
                                        return !addon.inclusion_only ? (
                                            plan.free_allocation && !plan.tiers ? (
                                                <td key={`${addon.name}-free-tiers-td`}>
                                                    <p className="text-secondary text-xs">
                                                        Not available on this plan.
                                                    </p>
                                                </td>
                                            ) : (
                                                <td key={`${addon.type}-tiers-td`}>
                                                    <AddonPlanTiers plan={addon.plans?.[0]} addon={addon} />
                                                </td>
                                            )
                                        ) : plan.free_allocation && !plan.tiers ? (
                                            <td key={`${addon.name}-free-tiers-td`}>
                                                <PricingTiers plan={plan} product={product} />
                                            </td>
                                        ) : (
                                            <td key={`${addon.type}-tiers-td`}>
                                                <AddonPlanTiers plan={addon.plans?.[i]} addon={addon} />
                                            </td>
                                        )
                                    })}
                                </tr>
                            ) : null
                        })}
                <tr>
                    <th colSpan={1} className="PlanTable__th__section rounded text-left">
                        <h3 className="mt-6 mb-2">
                            {product.type === 'platform_and_support' ? 'Platform' : 'Product'} features:
                        </h3>
                    </th>
                </tr>
                {fullyFeaturedPlan?.features?.map((feature, i) => (
                    <tr
                        key={`tr-${feature.key}`}
                        className={clsx(
                            i == fullyFeaturedPlan?.features?.length - 1 && !billing?.has_active_subscription
                                ? 'PlanTable__tr__border'
                                : ''
                        )}
                    >
                        <th
                            className={clsx(
                                'PlanTable__th__feature',
                                width && width < 600 && 'PlanTable__th__feature--reduced_padding',
                                i == fullyFeaturedPlan?.features?.length - 1 && 'PlanTable__th__last-feature'
                            )}
                        >
                            <Tooltip title={feature.description}>
                                <div
                                    className={
                                        comparisonModalHighlightedFeatureKey === feature.key
                                            ? 'border-b-2 border-danger-lighter px-1 pb-1 w-max'
                                            : undefined
                                    }
                                >
                                    <span>{feature.name}</span>
                                </div>
                            </Tooltip>
                        </th>
                        {plans?.map((plan) => (
                            <td key={`${plan.plan_key}-${feature.key}`}>
                                <PlanIcon
                                    feature={plan.features?.find(
                                        (thisPlanFeature) => feature.key === thisPlanFeature.key
                                    )}
                                    className="text-base"
                                />
                            </td>
                        ))}
                    </tr>
                ))}
                {!billing?.has_active_subscription && !product.inclusion_only && (
                    <>
                        <tr>
                            <th colSpan={1} className="PlanTable__th__section rounded text-left">
                                <h3 className="mt-6 mb-2">
                                    <Tooltip title="Organizations with any paid subscription get access to additional features.">
                                        <span>Included platform features:</span>
                                    </Tooltip>
                                </h3>
                            </th>
                        </tr>
                        {billing?.products
                            .filter((product) => product.inclusion_only)
                            .map((includedProduct) => {
                                const includedPlans = includedProduct.plans.filter(
                                    (plan) => plan.included_if == 'has_subscription' || plan.current_plan
                                )
                                return (
                                    <React.Fragment key={`inclusion-only-product-features-${includedProduct.type}`}>
                                        <tr>
                                            <th
                                                colSpan={3}
                                                className="PlanTable__th__section bg-primary justify-left rounded text-left mb-2"
                                            >
                                                <div className="flex items-center gap-x-2 my-2">
                                                    {getProductIcon(
                                                        includedProduct.name,
                                                        includedProduct.icon_key,
                                                        'text-2xl'
                                                    )}
                                                    <Tooltip title={includedProduct.description}>
                                                        <span className="font-bold">{includedProduct.name}</span>
                                                    </Tooltip>
                                                </div>
                                            </th>
                                        </tr>
                                        {includedPlans
                                            .find((plan: BillingPlanType) => plan.included_if == 'has_subscription')
                                            ?.features?.map((feature, i) => (
                                                <tr key={`tr-${feature.key}`}>
                                                    <th
                                                        className={clsx(
                                                            'text-secondary PlanTable__th__feature',
                                                            width &&
                                                                width < 600 &&
                                                                'PlanTable__th__feature--reduced_padding',
                                                            // If this is the last feature in the list, add a class to add padding to the bottom of
                                                            // the cell (which makes the whole row have the padding)
                                                            i ==
                                                                (includedPlans.find(
                                                                    (plan) => plan.included_if == 'has_subscription'
                                                                )?.features?.length || 0) -
                                                                    1
                                                                ? 'PlanTable__th__last-feature'
                                                                : ''
                                                        )}
                                                    >
                                                        <Tooltip title={feature.description}>
                                                            <span>{feature.name}</span>
                                                        </Tooltip>
                                                    </th>
                                                    {includedPlans?.map((plan) => (
                                                        <React.Fragment key={`${plan.plan_key}-${feature.key}`}>
                                                            {/* Some products don't have a free plan, so we need to pretend there is one 
                                                                        so the features line up in the correct columns in the UI. This is kind of 
                                                                        hacky because it assumes we only have 2 plans total, but it works for now.
                                                                    */}
                                                            {includedPlans?.length === 1 && (
                                                                <td>
                                                                    <PlanIcon
                                                                        feature={undefined}
                                                                        className="text-base"
                                                                    />
                                                                </td>
                                                            )}
                                                            <td>
                                                                <PlanIcon
                                                                    feature={plan.features?.find(
                                                                        (thisPlanFeature) =>
                                                                            feature.key === thisPlanFeature.key
                                                                    )}
                                                                    className="text-base"
                                                                />
                                                            </td>
                                                        </React.Fragment>
                                                    ))}
                                                </tr>
                                            ))}
                                    </React.Fragment>
                                )
                            })}
                    </>
                )}
            </tbody>
            {surveyID && <UnsubscribeSurveyModal product={product} />}
        </table>
    )
}

export const PlanComparisonModal = ({
    product,
    title,
    includeAddons = false,
    modalOpen,
    onClose,
}: {
    product: BillingProductV2Type
    title?: string
    includeAddons?: boolean
    modalOpen: boolean
    onClose?: () => void
}): JSX.Element | null => {
    return (
        <LemonModal isOpen={modalOpen} onClose={onClose}>
            <div className="PlanComparisonModal flex w-full h-full justify-center p-6">
                <div className="text-left bg-surface-primary rounded relative w-full">
                    {title ? <h2>{title}</h2> : <h2>{product.name} plans</h2>}
                    <PlanComparison product={product} includeAddons={includeAddons} />
                </div>
            </div>
        </LemonModal>
    )
}

const AddonPlanTiers = ({ plan, addon }: { plan: BillingPlanType; addon: BillingProductV2AddonType }): JSX.Element => {
    const [showTiers, setShowTiers] = useState(false)

    return showTiers ? (
        <>
            <PricingTiers plan={plan} product={addon} />
            <p className="mb-0">
                <Link onClick={() => setShowTiers(false)} className="text-xs">
                    Hide volume discounts
                </Link>
            </p>
        </>
    ) : (
        <>
            <p className="mb-1">
                <b>
                    First {convertLargeNumberToWords(plan?.tiers?.[0].up_to || 0, null)} {addon.unit}s free
                </b>
                , then just ${plan?.tiers?.[1].unit_amount_usd}.
            </p>
            <p className="mb-0">
                <Link onClick={() => setShowTiers(true)} className="text-xs">
                    Show volume discounts
                </Link>
            </p>
        </>
    )
}
