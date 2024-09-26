import { IconCheckCircle, IconWarning, IconX } from '@posthog/icons'
import { LemonCollapse, LemonModal, LemonTag, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { FEATURE_FLAGS, UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import React, { useState } from 'react'
import { getProductIcon } from 'scenes/products/Products'
import useResizeObserver from 'use-resize-observer'

import { BillingFeatureType, BillingPlanType, BillingProductV2AddonType, BillingProductV2Type } from '~/types'

import { convertLargeNumberToWords, getProration, getProrationMessage, getUpgradeProductLink } from './billing-utils'
import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

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
        <div className="flex items-center text-xs text-muted">
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

/**
 * Determines the pricing description for a given plan.
 *
 * @param {Object} plan
 * @param {boolean} plan.free_allocation - Indicates if the plan has a free allocation.
 * @param {boolean} plan.tiers - Indicates if the plan has tiers.
 * @param {string} plan.unit_amount_usd - The unit amount in USD.
 * @param {boolean} plan.contact_support - Indicates if the plan requires contacting support.
 * @param {string} plan.included_if - Condition for plan inclusion.
 * @returns {string} - The pricing description for the plan.
 */
function getPlanDescription(plan: BillingPlanType): string {
    if (plan.free_allocation && !plan.tiers) {
        return 'Free forever'
    } else if (plan.unit_amount_usd) {
        return `$${parseFloat(plan.unit_amount_usd).toFixed(0)} per month`
    } else if (plan.contact_support) {
        return 'Custom'
    } else if (plan.included_if === 'has_subscription') {
        return 'Usage-based - starting at $0 per month'
    }
    return '$0 per month'
}

export const AllProductsPlanComparison = ({
    product,
    includeAddons = false,
}: {
    product: BillingProductV2Type
    includeAddons?: boolean
}): JSX.Element | null => {
    const { billing, redirectPath, timeRemainingInSeconds, timeTotalInSeconds } = useValues(billingLogic)
    const { ref: planComparisonRef } = useResizeObserver()
    const { reportBillingUpgradeClicked, reportBillingDowngradeClicked } = useActions(eventUsageLogic)
    const currentPlanIndex = plans.findIndex((plan) => plan.current_plan)
    const { surveyID, comparisonModalHighlightedFeatureKey, billingProductLoading } = useValues(
        billingProductLogic({ product })
    )
    const { reportSurveyShown, setSurveyResponse, setBillingProductLoading } = useActions(
        billingProductLogic({ product })
    )
    const { featureFlags } = useValues(featureFlagLogic)

    const plans = product.plans?.filter(
        (plan) => !plan.included_if || plan.included_if == 'has_subscription' || plan.current_plan
    )
    if (plans?.length === 0) {
        return null
    }

    const nonInclusionProducts = billing?.products.filter((p) => !p.inclusion_only) || []
    const inclusionProducts = billing?.products.filter((p) => !!p.inclusion_only) || []
    const sortedProducts = nonInclusionProducts
        ?.filter((p) => p.type === product.type)
        .slice()
        .concat(nonInclusionProducts.filter((p) => p.type !== product.type))
    const platformAndSupportProduct = inclusionProducts.find((p) => p.type === 'platform_and_support')
    const platformAndSupportPlans = platformAndSupportProduct?.plans.filter((p) => !p.contact_support) || []

    const upgradeButtons = plans?.map((plan, i) => {
        return (
            <td key={`${plan.plan_key}-cta`} className="px-4 py-2">
                <BillingUpgradeCTA
                    to={
                        plan.contact_support
                            ? 'mailto:sales@posthog.com?subject=Enterprise%20plan%20request'
                            : i < currentPlanIndex
                            ? undefined // Downgrade action handled in onClick
                            : getUpgradeProductLink({
                                  product,
                                  redirectPath,
                                  includeAddons,
                              })
                    }
                    type={plan.current_plan || i < currentPlanIndex ? 'secondary' : 'primary'}
                    status={
                        plan.current_plan || (plan.included_if == 'has_subscription' && i >= currentPlanIndex)
                            ? 'default'
                            : 'alt'
                    }
                    fullWidth
                    center
                    disableClientSideRouting={!plan.contact_support}
                    disabledReason={
                        plan.included_if == 'has_subscription' && i >= currentPlanIndex
                            ? billing?.has_active_subscription
                                ? 'Unsubscribe from all products to remove'
                                : null
                            : plan.current_plan
                            ? 'Current plan'
                            : undefined
                    }
                    onClick={() => {
                        if (!plan.current_plan) {
                            setBillingProductLoading(product.type)
                            if (i < currentPlanIndex) {
                                setSurveyResponse('$survey_response_1', product.type)
                                reportSurveyShown(UNSUBSCRIBE_SURVEY_ID, product.type)
                                reportBillingDowngradeClicked(product.type)
                            } else {
                                reportBillingUpgradeClicked(product.type)
                            }
                        }
                    }}
                    loading={billingProductLoading === product.type && !plan.current_plan && !plan.contact_support}
                    data-attr={`upgrade-${plan.name}`}
                >
                    {plan.current_plan
                        ? 'Current plan'
                        : i < currentPlanIndex
                        ? 'Downgrade'
                        : plan.contact_support
                        ? 'Get in touch'
                        : plan.included_if == 'has_subscription' &&
                          i >= currentPlanIndex &&
                          !billing?.has_active_subscription
                        ? 'Upgrade'
                        : plan.free_allocation && !plan.tiers
                        ? 'Select' // Free plan
                        : 'Upgrade'}
                </BillingUpgradeCTA>
            </td>
        )
    })

    return (
        <div>
            {surveyID && <UnsubscribeSurveyModal product={product} />}
            <table className="w-full table-fixed max-w-[920px] mb-6 mt-2" ref={planComparisonRef}>
                <thead>
                    {/* Plan name header row */}
                    <tr>
                        <td />
                        {platformAndSupportPlans?.map((plan) => (
                            <td key={`plan-type-${plan.plan_key}`} className="px-4 py-2">
                                <h3 className="font-bold mb-0">{plan.name}</h3>
                            </td>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {/* Plan price row */}
                    <tr>
                        <td className="px-4 py-2 font-bold">Monthly {product.tiered && 'base '} price</td>
                        {platformAndSupportPlans?.map((plan) => {
                            const { prorationAmount, isProrated } = getProration({
                                timeRemainingInSeconds,
                                timeTotalInSeconds,
                                amountUsd: plan.unit_amount_usd,
                                hasActiveSubscription: billing?.has_active_subscription,
                            })
                            return (
                                <td key={`${plan.plan_key}-basePrice`} className="px-4 py-2 text-sm font-medium">
                                    {getPlanDescription(plan)}
                                    {isProrated && (
                                        <p className="text-xxs text-muted font-normal italic mt-2">
                                            {getProrationMessage(prorationAmount, plan.unit_amount_usd)}
                                        </p>
                                    )}
                                </td>
                            )
                        })}
                    </tr>
                    {/* CTA Row */}
                    <tr>
                        <td />
                        {upgradeButtons}
                    </tr>
                    {/* Inclusion products  */}
                    {inclusionProducts.reverse().map((includedProduct) => {
                        const includedPlans = includedProduct.plans.filter(
                            (plan) => plan.included_if == 'has_subscription' || plan.current_plan
                        )
                        return (
                            <React.Fragment key={`inclusion-only-product-features-${includedProduct.type}`}>
                                <tr className="border-b">
                                    {/* Inclusion product title row */}
                                    <th colSpan={3} className="justify-left rounded text-left mb-2 py-6">
                                        <div className="flex items-center gap-x-2 my-2">
                                            {getProductIcon(includedProduct.name, includedProduct.icon_key, 'text-2xl')}
                                            <Tooltip title={includedProduct.description}>
                                                <span className="font-bold">{includedProduct.name}</span>
                                            </Tooltip>
                                        </div>
                                    </th>
                                </tr>
                                {includedPlans
                                    .find((plan: BillingPlanType) => plan.included_if == 'has_subscription')
                                    ?.features?.map((feature) => (
                                        // Inclusion product feature row
                                        <tr key={`tr-${feature.key}`} className="border-b">
                                            <th className="text-muted py-3 pl-8 font-medium text-left">
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
                                                        <td className="p-4">
                                                            <PlanIcon feature={undefined} className="text-base" />
                                                        </td>
                                                    )}
                                                    <td className="p-4">
                                                        <PlanIcon
                                                            feature={plan.features?.find(
                                                                (thisPlanFeature) => feature.key === thisPlanFeature.key
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
                </tbody>
            </table>

            <h3>Product features breakdown:</h3>
            <LemonCollapse
                defaultActiveKey={product.type}
                panels={
                    sortedProducts.map((currentProduct) => ({
                        header: (
                            <span className="flex justify-start items-center gap-1">
                                {getProductIcon(currentProduct.name, currentProduct.icon_key, 'text-2xl')}
                                <span>
                                    {currentProduct.name} {currentProduct.type === product.type ? '(this product)' : ''}
                                </span>
                            </span>
                        ),
                        className: 'bg-bg-3000',
                        key: currentProduct.type,
                        content: (
                            <table className="w-full table-fixed max-w-[920px]" ref={planComparisonRef}>
                                <tbody>
                                    {/* Pricing row */}
                                    <tr className="">
                                        <th scope="row">
                                            {includeAddons && currentProduct.addons?.length > 0 && (
                                                <p className="ml-0">
                                                    <span className="font-bold">{currentProduct.name}</span>
                                                </p>
                                            )}
                                            <p className="ml-0 text-xs mt-1">Priced per {currentProduct.unit}</p>
                                        </th>
                                        {currentProduct.plans?.map((plan) => (
                                            <td key={`${plan.plan_key}-tiers-td`} className="p-4">
                                                <PricingTiers plan={plan} product={currentProduct} />
                                            </td>
                                        ))}
                                    </tr>
                                    <tr>
                                        <tr className="rounded text-left">
                                            <h4 className="mt-6 mb-2">Product Features:</h4>
                                        </tr>
                                    </tr>
                                    {currentProduct.plans[currentProduct.plans.length - 1]?.features?.map(
                                        (feature, i) => (
                                            <tr
                                                key={`tr-${feature.key}`}
                                                className={clsx(
                                                    i ==
                                                        currentProduct.plans[currentProduct.plans.length - 1]?.features
                                                            ?.length -
                                                            1 && !billing?.has_active_subscription
                                                        ? ''
                                                        : 'border-b'
                                                )}
                                            >
                                                <th className="text-muted py-3 pl-8 font-medium text-left">
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
                                                {currentProduct.plans?.map((plan) => (
                                                    <td key={`${plan.plan_key}-${feature.key}`} className="p-4">
                                                        <PlanIcon
                                                            feature={plan.features?.find(
                                                                (thisPlanFeature) => feature.key === thisPlanFeature.key
                                                            )}
                                                            className="text-base"
                                                        />
                                                    </td>
                                                ))}
                                            </tr>
                                        )
                                    )}
                                    {includeAddons && product.addons.length > 0 && (
                                        <tr>
                                            <th colSpan={1} className="PlanTable__th__section rounded text-left">
                                                <h3 className="mt-6 mb-6">Available add-ons:</h3>
                                            </th>
                                        </tr>
                                    )}
                                    {includeAddons &&
                                        currentProduct.addons
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
                                                    <tr
                                                        key={addon.name + 'pricing-row'}
                                                        className="PlanTable__tr__border"
                                                    >
                                                        <th scope="row">
                                                            <p className="ml-0">
                                                                <Tooltip title={addon.description}>
                                                                    <span className="font-bold cursor-default">
                                                                        {addon.name}
                                                                    </span>
                                                                </Tooltip>
                                                                <Tooltip
                                                                    title={
                                                                        addon.inclusion_only
                                                                            ? 'Automatically charged based on SDK config options and usage.'
                                                                            : 'If subscribed, charged on all usage.'
                                                                    }
                                                                >
                                                                    <LemonTag
                                                                        type={
                                                                            addon.inclusion_only ? 'option' : 'primary'
                                                                        }
                                                                        className="ml-2"
                                                                    >
                                                                        {addon.inclusion_only ? 'config' : 'add-on'}
                                                                    </LemonTag>
                                                                </Tooltip>
                                                            </p>
                                                            <p className="ml-0 text-xs text-muted mt-1">
                                                                Priced per {addon.unit}
                                                            </p>
                                                        </th>
                                                        {plans?.map((plan, i) => {
                                                            // If the parent plan is free, the addon isn't available
                                                            return !addon.inclusion_only ? (
                                                                plan.free_allocation && !plan.tiers ? (
                                                                    <td
                                                                        key={`${addon.name}-free-tiers-td`}
                                                                        className="p-4"
                                                                    >
                                                                        <p className="text-muted text-xs">
                                                                            Not available on this plan.
                                                                        </p>
                                                                    </td>
                                                                ) : (
                                                                    <td key={`${addon.type}-tiers-td`} className="p-4">
                                                                        <AddonPlanTiers
                                                                            plan={addon.plans?.[0]}
                                                                            addon={addon}
                                                                        />
                                                                    </td>
                                                                )
                                                            ) : plan.free_allocation && !plan.tiers ? (
                                                                <td key={`${addon.name}-free-tiers-td`} className="p-4">
                                                                    <PricingTiers plan={plan} product={product} />
                                                                </td>
                                                            ) : (
                                                                <td key={`${addon.type}-tiers-td`} className="p-4">
                                                                    <AddonPlanTiers
                                                                        plan={addon.plans?.[i]}
                                                                        addon={addon}
                                                                    />
                                                                </td>
                                                            )
                                                        })}
                                                    </tr>
                                                ) : null
                                            })}
                                </tbody>
                            </table>
                        ),
                    })) || []
                }
            />
        </div>
    )
}

export const AllProductsPlanComparisonModal = ({
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
                <div className="text-left bg-bg-light rounded relative w-full">
                    {title ? <h2>{title}</h2> : <h2>{product.name} plans</h2>}
                    <AllProductsPlanComparison product={product} includeAddons={includeAddons} />
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
