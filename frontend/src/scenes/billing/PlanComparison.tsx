import './PlanComparison.scss'

import { IconCheckCircle, IconWarning, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonModal, LemonSwitch, LemonTag, Link, Popover } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { FEATURE_FLAGS, UNSUBSCRIBE_SURVEY_ID } from 'lib/constants'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import React, { useEffect, useRef, useState } from 'react'
import { getProductIcon } from 'scenes/products/Products'
import { urls } from 'scenes/urls'
import useResizeObserver from 'use-resize-observer'

import { BillingProductV2AddonType, BillingProductV2Type, BillingV2FeatureType, BillingV2PlanType } from '~/types'

import { convertLargeNumberToWords, getProration, getUpgradeProductLink } from './billing-utils'
import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'
import { UnsubscribeSurveyModal } from './UnsubscribeSurveyModal'

export function PlanIcon({
    feature,
    className,
    timeDenominator,
}: {
    feature?: BillingV2FeatureType
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
    plan: BillingV2PlanType
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

export const BillingUpgradePopover = ({
    product,
    plan,
    includeAddons,
}: {
    product: BillingProductV2Type
    plan: BillingV2PlanType
    includeAddons: boolean
}): JSX.Element | null => {
    const { redirectPath } = useValues(billingLogic)
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)
    const [addonsEnabled, setAddonsEnabled] = useState<boolean[]>([])
    const [inputValue, setInputValue] = useState(500)
    const [addonsDict, setAddonsDict] = useState({})

    const [filteredAddons, setFilteredAddons] = useState(product.addons)
    useEffect(() => {
        if (plan.free_allocation && !plan.tiers) {
            setFilteredAddons([])
        } else {
            setFilteredAddons(
                product.addons?.filter((addon) => {
                    if (addon.inclusion_only) {
                        return false
                    }
                    return true
                })
            )
        }
        setAddonsEnabled(filteredAddons.map(() => false))
    }, [product])

    useEffect(() => {
        const addonsDict = {}
        for (let i = 0; i < filteredAddons.length; i++) {
            if (addonsEnabled[i]) {
                addonsDict[filteredAddons[i].type] = filteredAddons[i].plans[0].plan_key
            }
        }
        setAddonsDict(addonsDict)
    }, [addonsEnabled])

    return (
        <div>
            <h3>Configure your subscription</h3>
            {!plan.current_plan && !plan.free_allocation && includeAddons && filteredAddons.length > 0 && (
                <div className="mb-2">
                    <h4 className="mb-0">Enable add-ons</h4>
                    {filteredAddons.map((addon, i) => {
                        return (
                            <div key={addon.name} className="grid grid-cols-2 pl-2 pr-2">
                                <span>{addon.name}</span>
                                <LemonSwitch
                                    checked={addonsEnabled[i]}
                                    className="justify-self-end"
                                    onChange={(value) => {
                                        const newAddons = addonsEnabled.map((val, idx) => {
                                            if (idx == i) {
                                                return value
                                            }
                                            return val
                                        })
                                        setAddonsEnabled(newAddons)
                                    }}
                                />
                            </div>
                        )
                    })}
                </div>
            )}
            <h4 className="mb-0">Set a billing limit</h4>
            <LemonInput
                className="ml-2 mr-2"
                type="number"
                fullWidth={false}
                status="default"
                value={inputValue}
                onChange={(value) => value && setInputValue(value)}
                prefix={<b>$</b>}
                min={0}
                step={10}
                suffix={<>/ month</>}
                size="small"
            />

            <LemonButton
                className="float-right mt-4"
                status="default"
                type="primary"
                to={
                    plan.contact_support
                        ? 'mailto:sales@posthog.com?subject=Enterprise%20plan%20request'
                        : !plan.included_if
                        ? getUpgradeProductLink(
                              product,
                              plan.plan_key || '',
                              redirectPath,
                              false,
                              addonsDict,
                              inputValue
                          )
                        : // : plan.included_if == 'has_subscription' &&
                          //   i >= currentPlanIndex &&
                          //   !billing?.has_active_subscription
                          // ? urls.organizationBilling()
                          undefined
                }
                disableClientSideRouting={!plan.contact_support}
                onClick={() => {
                    if (!plan.current_plan) {
                        // TODO: add current plan key and new plan key
                        reportBillingUpgradeClicked(product.type)
                    }
                }}
            >
                Subscribe as configured
            </LemonButton>
        </div>
    )
}

export const PlanComparison = ({
    product,
    includeAddons = false,
}: {
    product: BillingProductV2Type
    includeAddons?: boolean
}): JSX.Element | null => {
    const plans = product.plans?.filter(
        (plan) => !plan.included_if || plan.included_if == 'has_subscription' || plan.current_plan
    )
    if (plans?.length === 0) {
        return null
    }

    const fullyFeaturedPlan = plans[plans.length - 1]
    const { billing, timeRemainingInSeconds, timeTotalInSeconds } = useValues(billingLogic)
    const { width, ref: planComparisonRef } = useResizeObserver()

    const currentPlanIndex = plans.findIndex((plan) => plan.current_plan)
    const { surveyID, comparisonModalHighlightedFeatureKey, upgradeOverlayOpen } = useValues(
        billingProductLogic({ product })
    )
    const { reportSurveyShown, setSurveyResponse, closeUpgradeOverlay, toggleUpgradeOverlay } = useActions(
        billingProductLogic({ product })
    )

    const { featureFlags } = useValues(featureFlagLogic)

    const upgradeButtons = plans?.map((plan, i) => {
        return (
            <td key={`${plan.plan_key}-cta`} className="PlanTable__td__upgradeButton">
                {!plan.free_allocation ? (
                    <Popover
                        overlay={<BillingUpgradePopover product={product} plan={plan} includeAddons={includeAddons} />}
                        visible={upgradeOverlayOpen}
                        onClickOutside={() => closeUpgradeOverlay()}
                        placement="bottom-end"
                        matchWidth={true}
                    >
                        <LemonButton
                            fullWidth
                            center
                            data-attr={`upgrade-${plan.name}`}
                            type={plan.current_plan || i < currentPlanIndex ? 'secondary' : 'primary'}
                            status={
                                plan.current_plan || (plan.included_if == 'has_subscription' && i >= currentPlanIndex)
                                    ? 'default'
                                    : 'alt'
                            }
                            onClick={() => !plan.current_plan && toggleUpgradeOverlay()}
                            disabledReason={plan.current_plan && "You're already subscribed to this plan"}
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
                                ? 'View products'
                                : plan.free_allocation && !plan.tiers
                                ? 'Select' // Free plan
                                : 'Subscribe'}
                        </LemonButton>
                    </Popover>
                ) : (
                    <LemonButton
                        fullWidth
                        center
                        data-attr={`upgrade-${plan.name}`}
                        type={plan.current_plan || i < currentPlanIndex ? 'secondary' : 'primary'}
                        status={
                            plan.current_plan || (plan.included_if == 'has_subscription' && i >= currentPlanIndex)
                                ? 'default'
                                : 'alt'
                        }
                        onClick={() => toggleUpgradeOverlay()}
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
                            ? 'View products'
                            : plan.free_allocation && !plan.tiers
                            ? 'Select' // Free plan
                            : 'Subscribe'}
                    </LemonButton>
                )}
                {/* <BillingUpgradeCTA
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
                            setUpgradeOverlayOpen(true)
                            // if (!plan.current_plan) {
                            //     // TODO: add current plan key and new plan key
                            //     reportBillingUpgradeClicked(product.type)
                            // }
                            // if (plan.included_if == 'has_subscription' && !plan.current_plan && i < currentPlanIndex) {
                            //     setSurveyResponse(product.type, '$survey_response_1')
                            //     reportSurveyShown(UNSUBSCRIBE_SURVEY_ID, product.type)
                            // }
                        }}
                        data-attr={`upgrade-${plan.name}`}
                    ></BillingUpgradeCTA> */}
            </td>
        )
    })

    return (
        <table className="PlanComparison w-full table-fixed" ref={planComparisonRef}>
            <thead>
                <tr>
                    <td />
                    {plans?.map((plan) => (
                        <td key={`plan-type-${plan.plan_key}`}>
                            <h2 className="font-bold">{plan.name}</h2>
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
                            <td key={`${plan.plan_key}-basePrice`} className="text-sm font-bold">
                                {plan.free_allocation && !plan.tiers
                                    ? 'Free forever'
                                    : plan.unit_amount_usd
                                    ? `$${parseFloat(plan.unit_amount_usd).toFixed(0)} per month`
                                    : plan.contact_support
                                    ? 'Custom'
                                    : plan.included_if == 'has_subscription'
                                    ? 'Free, included with any product subscription'
                                    : '$0 per month'}
                                {isProrated && (
                                    <p className="text-xxs text-muted font-normal italic mt-2">
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
                <tr>
                    <td />
                    {upgradeButtons}
                </tr>
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
                                        <p className="ml-0 text-xs text-muted mt-1">Priced per {addon.unit}</p>
                                    </th>
                                    {plans?.map((plan, i) => {
                                        // If the parent plan is free, the addon isn't available
                                        return !addon.inclusion_only ? (
                                            plan.free_allocation && !plan.tiers ? (
                                                <td key={`${addon.name}-free-tiers-td`}>
                                                    <p className="text-muted text-xs">Not available on this plan.</p>
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
                        <h3 className="mt-6 mb-2">Product Features:</h3>
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
                                                className="PlanTable__th__section bg-side justify-left rounded text-left mb-2"
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
                                            .find((plan: BillingV2PlanType) => plan.included_if == 'has_subscription')
                                            ?.features?.map((feature, i) => (
                                                <tr key={`tr-${feature.key}`}>
                                                    <th
                                                        className={clsx(
                                                            'text-muted PlanTable__th__feature',
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
    includeAddons = false,
    modalOpen,
    onClose,
}: {
    product: BillingProductV2Type
    includeAddons?: boolean
    modalOpen: boolean
    onClose?: () => void
}): JSX.Element | null => {
    return (
        <LemonModal isOpen={modalOpen} onClose={onClose}>
            <div className="PlanComparisonModal flex w-full h-full justify-center p-8">
                <div className="text-left bg-bg-light rounded relative w-full">
                    <h2>{product.name} plans</h2>
                    <PlanComparison product={product} includeAddons={includeAddons} />
                </div>
            </div>
        </LemonModal>
    )
}

const AddonPlanTiers = ({
    plan,
    addon,
}: {
    plan: BillingV2PlanType
    addon: BillingProductV2AddonType
}): JSX.Element => {
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
