import { LemonSelectOptions, LemonButton, LemonTable, LemonTag, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import { IconChevronRight, IconCheckmark, IconExpandMore, IconPlus, IconArticle } from 'lib/lemon-ui/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { BillingProductV2AddonType, BillingProductV2Type, BillingV2PlanType, BillingV2TierType } from '~/types'
import { summarizeUsage } from '../billing-utils'
import { BillingGauge } from './BillingGauge'
import { billingLogic } from '../billingLogic'
import { BillingLimitInput } from './BillingLimitInput'
import { billingProductLogic } from './billingProductLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { ProductPricingModal } from './ProductPricingModal'
import { PlanComparisonModal } from './PlanComparisonModal'

const getCurrentAndUpgradePlans = (
    product: BillingProductV2Type | BillingProductV2AddonType
): { currentPlan: BillingV2PlanType; upgradePlan: BillingV2PlanType; downgradePlan: BillingV2PlanType } => {
    const currentPlanIndex = product.plans.findIndex((plan) => plan.current_plan)
    const currentPlan = product.plans?.[currentPlanIndex]
    const upgradePlan = product.plans?.[currentPlanIndex + 1]
    const downgradePlan = product.plans?.[currentPlanIndex - 1]
    return { currentPlan, upgradePlan, downgradePlan }
}

export const getTierDescription = (
    tier: BillingV2TierType,
    i: number,
    product: BillingProductV2Type | BillingProductV2AddonType,
    interval: string
): string => {
    return i === 0
        ? `First ${summarizeUsage(tier.up_to)} ${product.unit}s / ${interval}`
        : tier.up_to
        ? `${summarizeUsage(product.tiers?.[i - 1].up_to || null)} - ${summarizeUsage(tier.up_to)}`
        : `> ${summarizeUsage(product.tiers?.[i - 1].up_to || null)}`
}

export const BillingProductAddon = ({ addon }: { addon: BillingProductV2AddonType }): JSX.Element => {
    const { billing, redirectPath } = useValues(billingLogic)
    const { deactivateProduct } = useActions(billingLogic)
    const { isPricingModalOpen } = useValues(billingProductLogic({ product: addon }))
    const { toggleIsPricingModalOpen } = useActions(billingProductLogic({ product: addon }))

    const productType = { plural: `${addon.unit}s`, singular: addon.unit }
    const tierDisplayOptions: LemonSelectOptions<string> = [
        { label: `Per ${productType.singular}`, value: 'individual' },
    ]

    if (billing?.has_active_subscription) {
        tierDisplayOptions.push({ label: `Current bill`, value: 'total' })
    }

    return (
        <div className="bg-side rounded p-6 flex flex-col">
            <div className="flex justify-between gap-x-4">
                <div className="flex gap-x-4">
                    {addon.image_url ? (
                        <img className="w-10 h-10" alt={`Logo for PostHog ${addon.name}`} src={addon.image_url} />
                    ) : null}
                    <div>
                        <div className="flex gap-x-2 items-center mt-0 mb-2 ">
                            <h4 className="leading-5 mb-1 font-bold">{addon.name}</h4>
                            {addon.subscribed && (
                                <div>
                                    <LemonTag type="purple" icon={<IconCheckmark />}>
                                        Subscribed
                                    </LemonTag>
                                </div>
                            )}
                        </div>
                        <p className="ml-0 mb-0">{addon.description}</p>
                    </div>
                </div>
                <div className="ml-4 mr-4 mt-2 self-center flex gap-x-2">
                    {addon.docs_url && (
                        <Tooltip title="Read the docs">
                            <LemonButton icon={<IconArticle />} status="stealth" size="small" to={addon.docs_url} />
                        </Tooltip>
                    )}
                    {addon.subscribed ? (
                        <>
                            <More
                                overlay={
                                    <>
                                        <LemonButton
                                            status="stealth"
                                            fullWidth
                                            onClick={() => deactivateProduct(addon.type)}
                                        >
                                            Remove addon
                                        </LemonButton>
                                    </>
                                }
                            />
                        </>
                    ) : addon.included ? (
                        <LemonTag type="purple" icon={<IconCheckmark />}>
                            Included with plan
                        </LemonTag>
                    ) : (
                        <>
                            <LemonButton
                                type="secondary"
                                disableClientSideRouting
                                onClick={() => {
                                    toggleIsPricingModalOpen()
                                }}
                            >
                                View pricing
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                icon={<IconPlus />}
                                size="small"
                                to={`/api/billing-v2/activation?products=${addon.type}:${
                                    getCurrentAndUpgradePlans(addon).upgradePlan?.plan_key
                                }${redirectPath && `&redirect_path=${redirectPath}`}`}
                                disableClientSideRouting
                            >
                                Add
                            </LemonButton>
                        </>
                    )}
                </div>
            </div>
            <ProductPricingModal
                modalOpen={isPricingModalOpen}
                onClose={toggleIsPricingModalOpen}
                product={addon}
                planKey={
                    addon.subscribed
                        ? getCurrentAndUpgradePlans(addon).currentPlan?.plan_key
                        : getCurrentAndUpgradePlans(addon).upgradePlan?.plan_key
                }
            />
        </div>
    )
}

export const BillingProduct = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const { billing, redirectPath, isOnboarding } = useValues(billingLogic)
    const { deactivateProduct } = useActions(billingLogic)
    const { customLimitUsd, showTierBreakdown, billingGaugeItems, isPricingModalOpen, isPlanComparisonModalOpen } =
        useValues(billingProductLogic({ product }))
    const {
        setIsEditingBillingLimit,
        setShowTierBreakdown,
        toggleIsPricingModalOpen,
        toggleIsPlanComparisonModalOpen,
    } = useActions(billingProductLogic({ product }))
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)

    const showUpgradeCTA = !product.subscribed && !product.contact_support && product.plans?.length
    const upgradePlan = getCurrentAndUpgradePlans(product).upgradePlan
    const currentPlan = getCurrentAndUpgradePlans(product).currentPlan
    const downgradePlan = getCurrentAndUpgradePlans(product).downgradePlan
    const additionalFeaturesOnUpgradedPlan = upgradePlan
        ? upgradePlan?.features?.filter(
              (feature) =>
                  !currentPlan?.features?.some((currentPlanFeature) => currentPlanFeature.name === feature.name)
          )
        : currentPlan?.features?.filter(
              (feature) =>
                  !downgradePlan?.features?.some((downgradePlanFeature) => downgradePlanFeature.name === feature.name)
          )

    const upgradeToPlanKey = upgradePlan?.plan_key
    const currentPlanKey = currentPlan?.plan_key

    const getUpgradeAllProductsLink = (): string => {
        let url = '/api/billing-v2/activation?products='
        url += `${product.type}:${upgradeToPlanKey},`
        if (product.addons?.length) {
            for (const addon of product.addons) {
                url += `${addon.type}:${addon.plans[0].plan_key},`
            }
        }
        // remove the trailing comma that will be at the end of the url
        url = url.slice(0, -1)
        if (redirectPath) {
            url += `&redirect_path=${redirectPath}`
        }
        return url
    }

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        700: 'medium',
    })

    const addonPriceColumns = product.addons
        // only get addons that are subscribed or were subscribed and have a projected amount
        ?.filter((addon) => addon.subscribed || parseFloat(addon.projected_amount_usd || ''))
        .map((addon) => ({
            title: `${addon.name} price`,
            dataIndex: `${addon.type}-price`,
        }))

    const tableColumns = [
        { title: `Priced per ${product.unit}`, dataIndex: 'volume' },
        { title: addonPriceColumns?.length > 0 ? 'Base price' : 'Price', dataIndex: 'basePrice' },
        ...(addonPriceColumns || []),
        { title: 'Current Usage', dataIndex: 'usage' },
        { title: 'Total', dataIndex: 'total' },
        { title: 'Projected Total', dataIndex: 'projectedTotal' },
    ]

    // TODO: SUPPORT NON-TIERED PRODUCT TYPES
    // still use the table, but the data will be different
    const tableTierData:
        | {
              volume: string
              basePrice: string
              [addonPrice: string]: string
              usage: string
              total: string
              projectedTotal: string
          }[]
        | undefined = product.tiers
        ?.map((tier, i) => {
            const addonPricesForTier = product.addons?.map((addon) => ({
                [`${addon.type}-price`]: `$${addon.tiers?.[i].unit_amount_usd}`,
            }))
            // take the tier.current_amount_usd and add it to the same tier level for all the addons
            const totalForTier =
                parseFloat(tier.current_amount_usd || '') +
                product.addons?.reduce((acc, addon) => acc + parseFloat(addon.tiers?.[i].current_amount_usd || ''), 0)
            const projectedTotalForTier =
                (tier.projected_amount_usd || 0) +
                product.addons?.reduce((acc, addon) => acc + (addon.tiers?.[i].projected_amount_usd || 0), 0)

            const tierData = {
                volume: getTierDescription(tier, i, product, billing?.billing_period?.interval || ''),
                basePrice: tier.unit_amount_usd !== '0' ? `$${tier.unit_amount_usd}` : 'Free',
                usage: summarizeUsage(tier.current_usage),
                total: `$${totalForTier || '0.00'}`,
                projectedTotal: `$${projectedTotalForTier || '0.00'}`,
            }
            // if there are any addon prices we need to include, put them in the table
            addonPricesForTier?.map((addonPrice) => {
                Object.assign(tierData, addonPrice)
            })
            return tierData
        })
        // Add a row at the end for the total
        .concat({
            volume: 'Total',
            basePrice: '',
            usage: `${summarizeUsage(product.current_usage ?? 0)}`,
            total: `$${product.current_amount_usd || '0.00'}`,
            // TODO: Make sure this projected total includes addons
            projectedTotal: `$${product.projected_amount_usd || '0.00'}`,
        })

    return (
        <div
            className={clsx('flex flex-wrap max-w-xl pb-12', {
                'flex-col pb-4': size === 'small',
            })}
            ref={ref}
        >
            <div className="border border-border rounded w-full bg-white">
                <div className="border-b border-border bg-mid p-4">
                    <div className="flex gap-4 items-center justify-between">
                        {product.image_url ? (
                            <img
                                className="w-10 h-10"
                                alt={`Logo for PostHog ${product.name}`}
                                src={product.image_url}
                            />
                        ) : null}
                        <div>
                            <h3 className="font-bold mb-0">{product.name}</h3>
                            <div>{product.description}</div>
                        </div>
                        <div className="flex grow justify-end gap-x-2 items-center">
                            {product.docs_url && (
                                <Tooltip title="Read the docs">
                                    <LemonButton
                                        icon={<IconArticle />}
                                        status="stealth"
                                        size="small"
                                        to={product.docs_url}
                                        className="justify-end"
                                    />
                                </Tooltip>
                            )}
                            {product.contact_support ? (
                                <>
                                    {product.subscribed && <p className="m-0">Need to manage your plan?</p>}
                                    <LemonButton
                                        type="primary"
                                        to="mailto:sales@posthog.com?subject=Enterprise%20plan%20request"
                                    >
                                        Contact support
                                    </LemonButton>
                                </>
                            ) : (
                                product.subscribed && (
                                    <More
                                        overlay={
                                            <>
                                                <LemonButton
                                                    status="stealth"
                                                    fullWidth
                                                    onClick={() => deactivateProduct(product.type)}
                                                >
                                                    Unsubscribe
                                                </LemonButton>
                                                {billing?.billing_period?.interval == 'month' && (
                                                    <LemonButton
                                                        fullWidth
                                                        status="stealth"
                                                        onClick={() => setIsEditingBillingLimit(true)}
                                                    >
                                                        Set billing limit
                                                    </LemonButton>
                                                )}
                                            </>
                                        }
                                    />
                                )
                            )}
                        </div>
                    </div>
                </div>
                <div className="px-8">
                    {product.percentage_usage > 1 ? (
                        <AlertMessage type={'error'}>
                            You have exceeded the {customLimitUsd ? 'billing limit' : 'free tier limit'} for this
                            product.
                        </AlertMessage>
                    ) : null}
                    <div className="flex w-full items-center gap-x-8">
                        {product.contact_support && !product.subscribed ? (
                            <>
                                <p className="m-0 p-8">
                                    Need additional platform and support (aka enterprise) features?{' '}
                                    <Link to="mailto:sales@posthog.com?subject=Enterprise%20plan%20request">
                                        Get in touch
                                    </Link>{' '}
                                    for a quick chat.
                                </p>
                            </>
                        ) : (
                            !isOnboarding && (
                                <>
                                    {product.tiered ? (
                                        <>
                                            {product.subscribed && (
                                                <LemonButton
                                                    icon={showTierBreakdown ? <IconExpandMore /> : <IconChevronRight />}
                                                    status="stealth"
                                                    onClick={() => setShowTierBreakdown(!showTierBreakdown)}
                                                />
                                            )}
                                            <div className="grow">
                                                <BillingGauge items={billingGaugeItems} />
                                            </div>
                                            {product.current_amount_usd ? (
                                                <div className="flex justify-end gap-8 flex-wrap items-end">
                                                    <Tooltip
                                                        title={`The current amount you have been billed for this ${billing?.billing_period?.interval} so far.`}
                                                        className="flex flex-col items-center"
                                                    >
                                                        <div className="font-bold text-3xl leading-7">
                                                            ${product.current_amount_usd}
                                                        </div>
                                                        <span className="text-xs text-muted">
                                                            {capitalizeFirstLetter(
                                                                billing?.billing_period?.interval || ''
                                                            )}
                                                            -to-date
                                                        </span>
                                                    </Tooltip>
                                                    {product.tiers && (
                                                        <Tooltip
                                                            title={
                                                                'This is roughly calculated based on your current bill and the remaining time left in this billing period.'
                                                            }
                                                            className="flex flex-col items-center justify-end"
                                                        >
                                                            <div className="font-bold text-muted text-lg leading-5">
                                                                ${product.projected_amount_usd || '0.00'}
                                                            </div>
                                                            <span className="text-xs text-muted">Predicted</span>
                                                        </Tooltip>
                                                    )}
                                                </div>
                                            ) : null}
                                        </>
                                    ) : (
                                        <div className="my-8">
                                            <Tooltip
                                                title={`The current amount you will be billed for this ${billing?.billing_period?.interval}.`}
                                                className="flex flex-col items-center"
                                            >
                                                <div className="font-bold text-3xl leading-7">
                                                    ${product.current_amount_usd}
                                                </div>
                                                <span className="text-xs text-muted">
                                                    per {billing?.billing_period?.interval || 'period'}
                                                </span>
                                            </Tooltip>
                                        </div>
                                    )}
                                </>
                            )
                        )}
                    </div>
                    {product.price_description ? (
                        <AlertMessage type="info">
                            <span dangerouslySetInnerHTML={{ __html: product.price_description }} />
                        </AlertMessage>
                    ) : null}
                    {/* Table with tiers */}
                    {showTierBreakdown && (
                        <div className="pl-16 pb-8">
                            {product.tiered && tableTierData ? (
                                <LemonTable
                                    borderedRows={false}
                                    size="xs"
                                    uppercaseHeader={false}
                                    display="stealth"
                                    columns={tableColumns}
                                    dataSource={tableTierData}
                                />
                            ) : (
                                <LemonTable
                                    borderedRows={false}
                                    size="xs"
                                    display="stealth"
                                    uppercaseHeader={false}
                                    columns={[
                                        { title: '', dataIndex: 'name' },
                                        { title: 'Total', dataIndex: 'total' },
                                    ]}
                                    dataSource={[
                                        {
                                            name: product.name,
                                            total: product.unit_amount_usd,
                                        },
                                    ]}
                                />
                            )}
                        </div>
                    )}
                    {!isOnboarding && product.addons?.length > 0 && (
                        <div className="pb-8">
                            <h4 className="mb-4">Addons</h4>
                            <div className="gap-y-4 flex flex-col">
                                {product.addons.map((addon, i) => {
                                    return <BillingProductAddon key={i} addon={addon} />
                                })}
                            </div>
                        </div>
                    )}
                </div>
                {(showUpgradeCTA || (isOnboarding && !product.contact_support)) && (
                    <div
                        className={`border-t border-border p-8 flex justify-between ${
                            product.subscribed ? 'bg-success-highlight' : 'bg-warning-highlight'
                        }`}
                    >
                        <div>
                            <h4 className={`${product.subscribed ? 'text-success-dark' : 'text-warning-dark'}`}>
                                You're on the {product.subscribed ? 'paid' : 'free'} plan for {product.name}.
                            </h4>
                            <p className="m-0 max-w-200">
                                {product.subscribed ? 'You now' : 'Upgrade to'} get sweet features such as{' '}
                                {additionalFeaturesOnUpgradedPlan?.map((feature, i) => {
                                    return (
                                        i < 3 && (
                                            <Tooltip key={feature.key} title={feature.description}>
                                                <b>{feature.name}, </b>
                                            </Tooltip>
                                        )
                                    )
                                })}
                                and more{!billing?.has_active_subscription && ', plus upgraded platform features'}.
                            </p>
                        </div>
                        {!product.subscribed && (
                            <div className="ml-4">
                                <div className="flex flex-wrap gap-x-2 gap-y-2">
                                    <LemonButton
                                        type="secondary"
                                        onClick={toggleIsPlanComparisonModalOpen}
                                        className="grow"
                                    >
                                        Compare plans
                                    </LemonButton>
                                    <LemonButton
                                        to={
                                            // if we're in onboarding we want to upgrade them to the product and the addons at once
                                            isOnboarding
                                                ? getUpgradeAllProductsLink()
                                                : // otherwise we just want to upgrade them to the product
                                                  `/api/billing-v2/activation?products=${
                                                      product.type
                                                  }:${upgradeToPlanKey}${
                                                      redirectPath && `&redirect_path=${redirectPath}`
                                                  }`
                                        }
                                        type="primary"
                                        icon={<IconPlus />}
                                        disableClientSideRouting
                                        onClick={() => {
                                            reportBillingUpgradeClicked(product.type)
                                        }}
                                        className="grow"
                                    >
                                        Upgrade
                                    </LemonButton>
                                </div>
                            </div>
                        )}
                        <PlanComparisonModal
                            product={product}
                            modalOpen={isPlanComparisonModalOpen}
                            onClose={toggleIsPlanComparisonModalOpen}
                        />
                    </div>
                )}
                <BillingLimitInput product={product} />
            </div>
            <ProductPricingModal
                modalOpen={isPricingModalOpen}
                onClose={toggleIsPricingModalOpen}
                product={product}
                planKey={product.subscribed ? currentPlanKey : upgradeToPlanKey}
            />
        </div>
    )
}
