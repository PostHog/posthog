import { LemonButton, LemonModal, LemonTag, Link } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconCheckmark, IconClose, IconWarning } from 'lib/lemon-ui/icons'
import { BillingProductV2AddonType, BillingProductV2Type, BillingV2FeatureType, BillingV2PlanType } from '~/types'
import './PlanComparisonModal.scss'
import { useActions, useValues } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { convertLargeNumberToWords, getUpgradeAllProductsLink } from '../billing-utils'
import { billingLogic } from '../billingLogic'

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
                    <IconClose className={`text-danger mx-4 ${className}`} />
                </>
            ) : feature.limit ? (
                <>
                    <IconWarning className={`text-warning mx-4 ${className}`} />
                    {feature.limit &&
                        `${convertLargeNumberToWords(feature.limit, null)} ${feature.unit && feature.unit}${
                            timeDenominator ? `/${timeDenominator}` : ''
                        }`}
                    {feature.note}
                </>
            ) : (
                <>
                    <IconCheckmark className={`text-success mx-4 ${className}`} />
                    {feature.note}
                </>
            )}
        </div>
    )
}

const getProductTiers = (
    plan: BillingV2PlanType,
    product: BillingProductV2Type | BillingProductV2AddonType
): JSX.Element => {
    const tiers = plan?.tiers

    return (
        <>
            {tiers ? (
                tiers?.map((tier, i) => (
                    <div
                        key={`${plan.key}-${product.type}-${tier.up_to}`}
                        className="flex justify-between items-center"
                    >
                        <span className="text-xs">
                            {convertLargeNumberToWords(tier.up_to, tiers[i - 1]?.up_to, true, product.unit)}
                        </span>
                        <span className="font-bold">
                            {i === 0 && parseFloat(tier.unit_amount_usd) === 0
                                ? 'Free'
                                : `$${parseFloat(tier.unit_amount_usd).toFixed(6)}`}
                        </span>
                    </div>
                ))
            ) : product?.free_allocation ? (
                <div key={`${plan.key}-${product.type}-tiers`} className="flex justify-between items-center">
                    <span className="text-xs">
                        Up to {convertLargeNumberToWords(product?.free_allocation, null)} {product?.unit}s/mo
                    </span>
                    <span className="font-bold">Free</span>
                </div>
            ) : null}
        </>
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
    const plans = product.plans
    if (plans?.length === 0) {
        return null
    }
    const fullyFeaturedPlan = plans[plans.length - 1]
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)
    const { redirectPath } = useValues(billingLogic)

    const upgradeButtons = plans?.map((plan) => {
        return (
            <td key={`${plan.key}-cta`}>
                <LemonButton
                    to={
                        includeAddons
                            ? getUpgradeAllProductsLink(product, plan.plan_key || '', redirectPath)
                            : `/api/billing-v2/activation?products=${product.type}:${plan.plan_key}&redirect_path=${redirectPath}`
                    }
                    type={plan.current_plan ? 'secondary' : 'primary'}
                    fullWidth
                    center
                    disableClientSideRouting
                    disabled={plan.current_plan}
                    onClick={() => {
                        if (!plan.current_plan) {
                            reportBillingUpgradeClicked(product.type)
                        }
                    }}
                >
                    {plan.current_plan ? 'Current plan' : 'Upgrade'}
                </LemonButton>
                {!plan.current_plan && includeAddons && product.addons?.length > 0 && (
                    <p className="text-center ml-0 mt-2 mb-0">
                        <Link
                            to={`/api/billing-v2/activation?products=${product.type}:${plan.plan_key}&redirect_path=${redirectPath}`}
                            className="text-muted text-xs"
                            disableClientSideRouting
                        >
                            or upgrade without addons
                        </Link>
                    </p>
                )}
            </td>
        )
    })

    return (
        <LemonModal isOpen={modalOpen} onClose={onClose}>
            <div className="PlanComparisonModal flex items-center w-full h-full justify-center p-8">
                <div className="text-left bg-white rounded-md relative w-full">
                    <h2>{product.name} plans</h2>
                    <table className="w-full table-fixed">
                        <thead>
                            <tr>
                                <td />
                                {plans?.map((plan) => (
                                    <td key={`plan-type-${plan.plan_key}`}>
                                        <h3 className="font-bold">
                                            {plan.free_allocation && !plan.tiers ? 'Free' : 'Paid'}
                                        </h3>
                                    </td>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {/* Pricing section */}
                            <tr>
                                <th
                                    colSpan={3}
                                    className="PlanTable__th__section bg-muted-light text-muted justify-left rounded text-left mb-2"
                                >
                                    <span>Pricing</span>
                                </th>
                            </tr>
                            <tr className="PlanTable__tr__border">
                                <td className="font-bold">Monthly base price</td>
                                {plans?.map((plan) => (
                                    <td key={`${plan.plan_key}-basePrice`} className="text-sm font-bold">
                                        {plan.free_allocation && !plan.tiers ? 'Free forever' : '$0 per month'}
                                    </td>
                                ))}
                            </tr>

                            <tr className={'PlanTable__tr__border'}>
                                <th scope="row">
                                    {includeAddons && product.addons?.length > 0 && (
                                        <p className="ml-0">
                                            <span className="font-bold">{product.name}</span>
                                        </p>
                                    )}
                                    <p className="ml-0 text-xs text-muted mt-1">Priced per {product.unit}</p>
                                </th>
                                {plans?.map((plan) => (
                                    <td key={`${plan.plan_key}-tiers-td`}>{getProductTiers(plan, product)}</td>
                                ))}
                            </tr>

                            {includeAddons &&
                                product.addons?.map((addon) => {
                                    return addon.tiered ? (
                                        <tr key={addon.name + 'pricing-row'} className={'PlanTable__tr__border'}>
                                            <th scope="row">
                                                <p className="ml-0">
                                                    <span className="font-bold">{addon.name}</span>
                                                    <LemonTag type="purple" className="ml-2">
                                                        addon
                                                    </LemonTag>
                                                </p>
                                                <p className="ml-0 text-xs text-muted mt-1">Priced per {addon.unit}</p>
                                            </th>
                                            {plans?.map((plan) =>
                                                // If the plan is free, the addon isn't available
                                                plan.free_allocation && !plan.tiers ? (
                                                    <td key={`${addon.name}-free-tiers-td`}>
                                                        <p className="text-muted text-xs">
                                                            Not available on this plan.
                                                        </p>
                                                    </td>
                                                ) : (
                                                    <td key={`${addon.type}-tiers-td`}>
                                                        {getProductTiers(addon.plans?.[0], addon)}
                                                    </td>
                                                )
                                            )}
                                        </tr>
                                    ) : null
                                })}

                            <tr>
                                <td />
                                {upgradeButtons}
                            </tr>
                            <tr>
                                <th
                                    colSpan={3}
                                    className="PlanTable__th__section bg-muted-light text-muted justify-left rounded text-left mb-2"
                                >
                                    <span>Features</span>
                                </th>
                            </tr>

                            {fullyFeaturedPlan?.features?.map((feature) => (
                                <tr key={`tr-${feature.key}`}>
                                    <th>
                                        <Tooltip title={feature.description}>{feature.name}</Tooltip>
                                    </th>
                                    {plans?.map((plan) => (
                                        <td key={`${plan.plan_key}-${feature.key}`}>
                                            <PlanIcon
                                                feature={plan.features?.find(
                                                    (thisPlanFeature) => feature.key === thisPlanFeature.key
                                                )}
                                                className={'text-base'}
                                            />
                                        </td>
                                    ))}
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </LemonModal>
    )
}
