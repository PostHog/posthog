import { LemonSelectOptions, LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import { IconChevronRight, IconCheckmark, IconExpandMore, IconPlus, IconArticle } from 'lib/lemon-ui/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { BillingProductV2AddonType, BillingProductV2Type, BillingV2TierType } from '~/types'
import { convertUsageToAmount, summarizeUsage } from '../billing-utils'
import { BillingGauge } from './BillingGauge'
import { billingLogic } from '../billingLogic'
import { BillingLimitInput } from './BillingLimitInput'
import { billingProductLogic } from './billingProductLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

export const BillingProductAddon = ({ addon }: { addon: BillingProductV2AddonType }): JSX.Element => {
    const { billing } = useValues(billingLogic)
    const { deactivateProduct } = useActions(billingLogic)

    const productType = { plural: `${addon.unit}s`, singular: addon.unit }
    const tierDisplayOptions: LemonSelectOptions<string> = [
        { label: `Per ${productType.singular}`, value: 'individual' },
    ]

    if (billing?.has_active_subscription) {
        tierDisplayOptions.push({ label: `Current bill`, value: 'total' })
    }

    // This assumes that the first plan is the free plan, and there is only one other plan that is paid
    // If there are more than two plans for single product in the future we need to make this smarter
    const upgradeToPlanKey = addon.plans?.filter((plan) => !plan.current_plan)[0]?.plan_key

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
                    ) : (
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            size="small"
                            to={`/api/billing-v2/activation?products=${addon.type}:${upgradeToPlanKey}`}
                            disableClientSideRouting
                        >
                            Add
                        </LemonButton>
                    )}
                </div>
            </div>
        </div>
    )
}

export const BillingProduct = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const { billing } = useValues(billingLogic)
    const { deactivateProduct } = useActions(billingLogic)
    const { customLimitUsd, showTierBreakdown, billingGaugeItems } = useValues(billingProductLogic({ product }))
    const { setIsEditingBillingLimit, setShowTierBreakdown } = useActions(billingProductLogic({ product }))
    const { reportBillingUpgradeClicked } = useActions(eventUsageLogic)

    const productType = { plural: `${product.unit}s`, singular: product.unit }
    // This assumes that the first plan is the free plan, and there is only one other plan that is paid
    // If there are more than two plans for single product in the future we need to make this smarter
    const upgradeToPlanKey = product.plans?.filter((plan) => !plan.current_plan)[0]?.plan_key

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        700: 'medium',
    })

    const tierDisplayOptions: LemonSelectOptions<string> = [
        { label: `Per ${productType.singular}`, value: 'individual' },
    ]

    const getTierDescription = (tier: BillingV2TierType, i: number): string => {
        return i === 0
            ? `First ${summarizeUsage(tier.up_to)} ${productType.plural} / ${billing?.billing_period?.interval}`
            : tier.up_to
            ? `${summarizeUsage(product.tiers?.[i - 1].up_to || null)} - ${summarizeUsage(tier.up_to)}`
            : `> ${summarizeUsage(product.tiers?.[i - 1].up_to || null)}`
    }

    const addonPriceColumns = product.addons
        // only get addons that are subscribed or were subscribed and have a projected amount
        .filter((addon) => addon.subscribed || parseFloat(addon.projected_amount_usd || ''))
        .map((addon) => ({
            title: `${addon.name} price`,
            dataIndex: `${addon.type}-price`,
        }))

    const tableColumns = [
        { title: `Priced per ${product.unit}`, dataIndex: 'volume' },
        { title: addonPriceColumns.length > 0 ? 'Base price' : 'Price', dataIndex: 'basePrice' },
        ...addonPriceColumns,
        { title: 'Current Usage', dataIndex: 'usage' },
        { title: 'Total', dataIndex: 'total' },
        { title: 'Projected Total', dataIndex: 'projectedTotal' },
    ]

    console.log(tableColumns)

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
            const addonPricesForTier = product.addons.map((addon) => ({
                [`${addon.type}-price`]: `$${addon.tiers?.[i].unit_amount_usd}`,
            }))
            // take the tier.current_amount_usd and add it to the same tier level for all the addons
            const totalForTier =
                parseFloat(tier.current_amount_usd || '') +
                product.addons.reduce((acc, addon) => acc + parseFloat(addon.tiers?.[i].current_amount_usd || ''), 0)
            const projectedTotalForTier =
                (tier.projected_amount_usd || 0) +
                product.addons.reduce((acc, addon) => acc + (addon.tiers?.[i].projected_amount_usd || 0), 0)

            const tierData = {
                volume: getTierDescription(tier, i),
                basePrice: tier.unit_amount_usd !== '0' ? `$${tier.unit_amount_usd}` : 'Free',
                usage: summarizeUsage(tier.current_usage),
                total: `$${totalForTier || '0.00'}`,
                projectedTotal: `$${projectedTotalForTier || '0.00'}`,
            }
            // if there are any addon prices we need to include, put them in the table
            addonPricesForTier.map((addonPrice) => {
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

    if (billing?.has_active_subscription) {
        tierDisplayOptions.push({ label: `Current bill`, value: 'total' })
    }

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
                        <div className="flex grow justify-end gap-x-2">
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
                            {!product.subscribed ? (
                                <LemonButton
                                    to={`/api/billing-v2/activation?products=${product.type}:${upgradeToPlanKey}`}
                                    type="primary"
                                    icon={<IconPlus />}
                                    disableClientSideRouting
                                    onClick={() => {
                                        reportBillingUpgradeClicked(product.type)
                                    }}
                                >
                                    Upgrade
                                </LemonButton>
                            ) : (
                                <More
                                    overlay={
                                        <>
                                            <LemonButton
                                                status="stealth"
                                                fullWidth
                                                onClick={() => deactivateProduct(product.type)}
                                            >
                                                Downgrade
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
                            )}
                        </div>
                    </div>
                </div>
                <div className="p-8 border-b border-border">
                    <ul className="space-y-2">
                        <li>
                            <IconCheckmark className="text-success text-lg" /> A great thing about this product
                        </li>
                        <li>
                            <IconCheckmark className="text-success text-lg" /> Another great thing about this product
                        </li>
                        <li>
                            <IconCheckmark className="text-success text-lg" /> Another great thing about this product
                        </li>
                        <li>
                            <IconCheckmark className="text-success text-lg" /> Another great thing about this product
                        </li>
                    </ul>
                </div>
                <div className="px-8">
                    {product.percentage_usage > 1 ? (
                        <AlertMessage type={'error'}>
                            You have exceeded the {customLimitUsd ? 'billing limit' : 'free tier limit'} for this
                            product.
                        </AlertMessage>
                    ) : null}
                    <div className="flex w-full items-center gap-x-8">
                        <LemonButton
                            icon={showTierBreakdown ? <IconExpandMore /> : <IconChevronRight />}
                            status="stealth"
                            onClick={() => setShowTierBreakdown(!showTierBreakdown)}
                        />
                        <div className="grow">{product.tiered && <BillingGauge items={billingGaugeItems} />}</div>
                        {product.current_amount_usd ? (
                            <div className="flex justify-end gap-8 flex-wrap items-end">
                                <Tooltip
                                    title={`The current amount you have been billed for this ${billing?.billing_period?.interval} so far.`}
                                    className="flex flex-col items-center"
                                >
                                    <div className="font-bold text-3xl leading-7">${product.current_amount_usd}</div>
                                    <span className="text-xs text-muted">
                                        {capitalizeFirstLetter(billing?.billing_period?.interval || '')}-to-date
                                    </span>
                                </Tooltip>
                                {product.tiered && product.tiers && (
                                    <Tooltip
                                        title={
                                            'This is roughly calculated based on your current bill and the remaining time left in this billing period.'
                                        }
                                        className="flex flex-col items-center justify-end"
                                    >
                                        <div className="font-bold text-muted text-lg leading-5">
                                            $
                                            {product.projected_usage
                                                ? convertUsageToAmount(product.projected_usage, product.tiers)
                                                : '0.00'}
                                        </div>
                                        <span className="text-xs text-muted">Predicted</span>
                                    </Tooltip>
                                )}
                            </div>
                        ) : null}
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
                    {product.addons?.length > 0 && (
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
                <BillingLimitInput product={product} />
            </div>
        </div>
    )
}
