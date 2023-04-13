import { LemonButton, LemonModal } from '@posthog/lemon-ui'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { IconCheckmark, IconClose, IconWarning } from 'lib/lemon-ui/icons'
import { BillingProductV2Type, BillingV2FeatureType, BillingV2PlanType } from '~/types'
import './PlanComparisonModal.scss'
import { useActions } from 'kea'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

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

const convertLargeNumberToWords = (
    // The number to convert
    num: number | null,
    // The previous tier's number
    previousNum: number | null,
    // Whether we will be showing multiple tiers (to denote the first tier with 'first')
    multipleTiers: boolean = false,
    // The product type (to denote the unit)
    productType: BillingProductV2Type['type'] | null = null
): string => {
    if (num === null && previousNum) {
        return `${convertLargeNumberToWords(previousNum, null)} +`
    }
    if (num === null) {
        return ''
    }

    let denominator = 1

    if (num >= 1000000) {
        denominator = 1000000
    } else if (num >= 1000) {
        denominator = 1000
    }

    return `${previousNum ? `${(previousNum / denominator).toFixed(0)}-` : multipleTiers ? 'First ' : ''}${(
        num / denominator
    ).toFixed(0)}${denominator === 1000000 ? ' million' : denominator === 1000 ? 'k' : ''}${
        !previousNum && multipleTiers ? ` ${productType}/mo` : ''
    }`
}

const getProductTiers = (plan: BillingV2PlanType, product: BillingProductV2Type): JSX.Element => {
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
                            {convertLargeNumberToWords(tier.up_to, tiers[i - 1]?.up_to, true, product.usage_key)}
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
                        Up to {convertLargeNumberToWords(product?.free_allocation, null)} {product?.usage_key}/mo
                    </span>
                    <span className="font-bold">Free</span>
                </div>
            ) : null}
        </>
    )
}

export const PlanComparisonModal = ({
    product,
    modalOpen,
    onClose,
}: {
    product: BillingProductV2Type
    modalOpen: boolean
    onClose?: () => void
}): JSX.Element | null => {
    const plans = product.plans
    if (plans?.length === 0) {
        return null
    }
    const fullyFeaturedPlan = plans[plans.length - 1]
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)

    const upgradeButtons = plans?.map((plan) => {
        return (
            <td key={`${plan.key}-cta`}>
                <LemonButton
                    to={`/api/billing-v2/activation?products=${product.type}:${plan.plan_key}`}
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
                                    <p className="ml-0 text-xs text-muted mt-1">Priced per {product.unit}</p>
                                </th>
                                {plans?.map((plan) => (
                                    <td key={`${plan.plan_key}-tiers-td`}>{getProductTiers(plan, product)}</td>
                                ))}
                            </tr>

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
