import { LemonSelectOptions, LemonButton, LemonTable, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import { IconChevronRight, IconCheckmark, IconExpandMore, IconPlus } from 'lib/lemon-ui/icons'
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

    const getTierDescription = (tier: BillingV2TierType, i: number): string => {
        return i === 0
            ? `First ${summarizeUsage(tier.up_to)} ${productType.plural} / ${billing?.billing_period?.interval}`
            : tier.up_to
            ? `${summarizeUsage(addon.tiers?.[i - 1].up_to || null)} - ${summarizeUsage(tier.up_to)}`
            : `> ${summarizeUsage(addon.tiers?.[i - 1].up_to || null)}`
    }

    // TODO: SUPPORT NON-TIERED PRODUCT TYPES
    // still use the table, but the data will be different
    const tableTierData:
        | {
              volume: string
              price: string
              usage: string
              total: string
              projectedTotal: string
          }[]
        | undefined = addon.tiers
        ?.map((tier, i) => ({
            volume: getTierDescription(tier, i),
            price: tier.unit_amount_usd !== '0' ? `$${tier.unit_amount_usd}` : 'Free',
            usage: summarizeUsage(tier.current_usage),
            total: `$${tier.current_amount_usd || '0.00'}`,
            projectedTotal: `$${tier.projected_amount_usd || '0.00'}`,
        }))
        .concat({
            volume: 'Total',
            price: '',
            usage: `${summarizeUsage(addon.current_usage ?? 0)}`,
            total: `$${addon.current_amount_usd || '0.00'}`,
            projectedTotal: `$${addon.projected_amount_usd || '0.00'}`,
        })

    if (billing?.has_active_subscription) {
        tierDisplayOptions.push({ label: `Current bill`, value: 'total' })
    }

    return (
        <div className="flex flex-col">
            <div className="bg-side rounded p-6 flex justify-between gap-x-4">
                <div className="flex gap-x-4">
                    {addon.image_url ? (
                        <img className="w-10 h-10" alt={`Logo for PostHog ${addon.name}`} src={addon.image_url} />
                    ) : null}
                    <div>
                        <h5 className="mt-0 mb-2 leading-5">{addon.name}</h5>
                        <p className="ml-0 mb-0">
                            {addon.description}
                            <br />
                            <Link>Learn more</Link> or <Link>view pricing</Link>.
                        </p>
                    </div>
                </div>
                <div className="ml-4 mr-4 mt-2 self-center">
                    {addon.subscribed ? (
                        <More
                            overlay={
                                <>
                                    <LemonButton
                                        status="stealth"
                                        fullWidth
                                        onClick={() => deactivateProduct(addon.type)}
                                    >
                                        Downgrade
                                    </LemonButton>
                                </>
                            }
                        />
                    ) : (
                        <LemonButton
                            type="primary"
                            icon={<IconPlus />}
                            size="small"
                            to={`/api/billing-v2/activation?products=${addon.type}:${addon.plans[0]}`}
                            disableClientSideRouting
                        >
                            Add
                        </LemonButton>
                    )}
                </div>
            </div>
            <div className="pl-16 pb-8">
                {/* TODO: We actually want to show this table regardless if there is an active sub */}
                {billing?.has_active_subscription && (
                    <>
                        {addon.tiered && tableTierData ? (
                            <LemonTable
                                borderedRows={false}
                                size="xs"
                                uppercaseHeader={false}
                                display="stealth"
                                columns={[
                                    { title: '', dataIndex: 'volume' },
                                    {
                                        title: `Price / ${addon.unit}`,
                                        dataIndex: 'price',
                                    },
                                    { title: 'Current Usage', dataIndex: 'usage' },
                                    { title: 'Total', dataIndex: 'total' },
                                    {
                                        title: 'Projected Total',
                                        dataIndex: 'projectedTotal',
                                    },
                                ]}
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
                                        name: addon.name,
                                        total: addon.unit_amount_usd,
                                    },
                                ]}
                            />
                        )}
                    </>
                )}
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

    // TODO: SUPPORT NON-TIERED PRODUCT TYPES
    // still use the table, but the data will be different
    const tableTierData:
        | {
              volume: string
              price: string
              usage: string
              total: string
              projectedTotal: string
          }[]
        | undefined = product.tiers
        ?.map((tier, i) => ({
            volume: getTierDescription(tier, i),
            price: tier.unit_amount_usd !== '0' ? `$${tier.unit_amount_usd}` : 'Free',
            usage: summarizeUsage(tier.current_usage),
            total: `$${tier.current_amount_usd || '0.00'}`,
            projectedTotal: `$${tier.projected_amount_usd || '0.00'}`,
        }))
        .concat({
            volume: 'Total',
            price: '',
            usage: `${summarizeUsage(product.current_usage ?? 0)}`,
            total: `$${product.current_amount_usd || '0.00'}`,
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
            <div className="border border-border rounded w-full">
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

                        {!product.subscribed ? (
                            <LemonButton
                                to={`/api/billing-v2/activation?products=${product.type}:${product.plans[0]}`}
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
                            <div className="flex grow justify-end">
                                <div className="flex self-center">
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
                                </div>
                            </div>
                        )}
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
                                    columns={[
                                        { title: '', dataIndex: 'volume' },
                                        { title: `Price / ${product.unit}`, dataIndex: 'price' },
                                        { title: 'Current Usage', dataIndex: 'usage' },
                                        { title: 'Total', dataIndex: 'total' },
                                        { title: 'Projected Total', dataIndex: 'projectedTotal' },
                                    ]}
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
                    {product.addons.length > 0 && (
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
