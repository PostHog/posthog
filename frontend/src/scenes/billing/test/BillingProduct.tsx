import { LemonSelectOptions, LemonButton, LemonTable, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import { IconChevronRight, IconCheckmark, IconExpandMore, IconPlus } from 'lib/lemon-ui/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { BillingProductV2Type, BillingV2TierType } from '~/types'
import { convertUsageToAmount, summarizeUsage } from '../billing-utils'
import { BillingGauge } from './BillingGauge'
import { billingLogic } from '../billingLogic'
import { BillingLimitInput } from './BillingLimitInput'
import { billingProductLogic } from './billingProductLogic'
import { capitalizeFirstLetter } from 'lib/utils'

export const BillingProduct = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const { billing } = useValues(billingLogic)
    const { customLimitUsd, showTierBreakdown, billingGaugeItems } = useValues(billingProductLogic({ product }))
    const { setIsEditingBillingLimit, setShowTierBreakdown } = useActions(billingProductLogic({ product }))

    const productType = { plural: product.type, singular: product.type.slice(0, -1) }

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
            usage: 'FIX ME',
            total: `$${tier.current_amount_usd || '$0.00'}`,
            projectedTotal: 'FIX ME',
        }))
        .concat({
            volume: 'Total',
            price: '',
            usage: 'FIX ME',
            total: `$${product.current_amount_usd || '$0.00'}`,
            projectedTotal: 'FIX ME',
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
                    <div className="flex gap-4 items-center">
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
                        {product.current_amount_usd && billing?.billing_period?.interval == 'month' ? (
                            <div className="flex grow justify-end">
                                <div className="flex self-center">
                                    <More
                                        overlay={
                                            <>
                                                <LemonButton fullWidth status="stealth">
                                                    Manage plan
                                                </LemonButton>
                                                <LemonButton
                                                    fullWidth
                                                    status="stealth"
                                                    onClick={() => setIsEditingBillingLimit(true)}
                                                >
                                                    Set billing limit
                                                </LemonButton>
                                            </>
                                        }
                                    />
                                </div>
                            </div>
                        ) : null}
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
                            {/* TODO: We actually want to show this table regardless if there is an active sub */}
                            {billing?.has_active_subscription && (
                                <>
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
                                </>
                            )}
                        </div>
                    )}
                    <div className="pb-8">
                        <h4 className="mb-4">Addons</h4>
                        <div className="gap-y-4 flex flex-col">
                            <div className="bg-side rounded p-6 flex justify-between gap-x-4">
                                {product.image_url ? (
                                    <img
                                        className="w-10 h-10"
                                        alt={`Logo for PostHog ${product.name}`}
                                        src={product.image_url}
                                    />
                                ) : null}
                                <div>
                                    <h5 className="mt-0 mb-2 leading-5">Group Analytics</h5>
                                    <p className="ml-0 mb-0">
                                        Some descriptor text. Group your peeps into organizations, etc, so you can track
                                        events for the group as a whole. Starting at $0.00003 per event.{' '}
                                        <Link>Learn more</Link> or <Link>view pricing</Link>.
                                    </p>
                                </div>
                                <div className="ml-4 mr-4 mt-2 self-center">
                                    <LemonButton type="primary" icon={<IconPlus />} size="small">
                                        Add
                                    </LemonButton>
                                </div>
                            </div>
                            <div className="bg-side rounded p-6 flex justify-between gap-x-4">
                                {product.image_url ? (
                                    <img
                                        className="w-10 h-10"
                                        alt={`Logo for PostHog ${product.name}`}
                                        src={product.image_url}
                                    />
                                ) : null}
                                <div>
                                    <h5 className="mt-0 mb-2 leading-5">CDP</h5>
                                    <p className="ml-0 mb-0">
                                        Some descriptor text. Some descriptor text. Send your data wherever you need it,
                                        however you need it. Starting at $0.00003 per event. <Link>Learn more</Link> or{' '}
                                        <Link>view pricing</Link>.
                                    </p>
                                </div>
                                <div className="ml-4 mr-4 mt-2 self-center">
                                    <LemonButton type="primary" icon={<IconPlus />} size="small">
                                        Add
                                    </LemonButton>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
                <BillingLimitInput product={product} />
            </div>
        </div>
    )
}
