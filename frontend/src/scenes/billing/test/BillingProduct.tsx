import { LemonSelectOptions, LemonButton, LemonInput, LemonTable } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues, useActions } from 'kea'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import { IconChevronRight, IconCheckmark, IconExpandMore } from 'lib/lemon-ui/icons'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useState, useEffect, useMemo } from 'react'
import { BillingProductV2Type, BillingV2TierType } from '~/types'
import { convertAmountToUsage, convertUsageToAmount, summarizeUsage } from '../billing-utils'
import { BillingGaugeProps, BillingGauge } from '../BillingGauge'
import { billingLogic } from '../billingLogic'

const DEFAULT_BILLING_LIMIT = 500

export const BillingProduct = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const { billing, billingLoading } = useValues(billingLogic)
    const { updateBillingLimits } = useActions(billingLogic)

    // The actual stored billing limit
    const customLimitUsd = billing?.custom_limits_usd?.[product.type]
    const [isEditingBillingLimit, setIsEditingBillingLimit] = useState(false)
    const [showTierBreakdown, setShowTierBreakdown] = useState(false)
    const [billingLimitInput, setBillingLimitInput] = useState<number | undefined>(DEFAULT_BILLING_LIMIT)

    const billingLimitAsUsage = product.tiers
        ? isEditingBillingLimit
            ? convertAmountToUsage(`${billingLimitInput}`, product.tiers)
            : convertAmountToUsage(customLimitUsd || '', product.tiers)
        : 0

    const productType = { plural: product.type, singular: product.type.slice(0, -1) }

    const updateBillingLimit = (value: number | undefined): any => {
        const actuallyUpdateLimit = (): void => {
            updateBillingLimits({
                [product.type]: typeof value === 'number' ? `${value}` : null,
            })
        }
        if (value === undefined) {
            return actuallyUpdateLimit()
        }

        const newAmountAsUsage = product.tiers ? convertAmountToUsage(`${value}`, product.tiers) : 0

        if (product.current_usage && newAmountAsUsage < product.current_usage) {
            LemonDialog.open({
                title: 'Billing limit warning',
                description:
                    'Your new billing limit will be below your current usage. Your bill will not increase for this period but parts of the product will stop working and data may be lost.',
                primaryButton: {
                    status: 'danger',
                    children: 'I understand',
                    onClick: () => actuallyUpdateLimit(),
                },
                secondaryButton: {
                    children: 'I changed my mind',
                },
            })
            return
        }

        if (product.projected_usage && newAmountAsUsage < product.projected_usage) {
            LemonDialog.open({
                title: 'Billing limit warning',
                description:
                    'Your predicted usage is above your billing limit which is likely to result in usage being throttled.',
                primaryButton: {
                    children: 'I understand',
                    onClick: () => actuallyUpdateLimit(),
                },
                secondaryButton: {
                    children: 'I changed my mind',
                },
            })
            return
        }

        return actuallyUpdateLimit()
    }

    useEffect(() => {
        if (!billingLoading) {
            setIsEditingBillingLimit(false)
        }
    }, [billingLoading])

    useEffect(() => {
        setBillingLimitInput(
            parseInt(customLimitUsd || '0') ||
                (product.tiers
                    ? parseInt(convertUsageToAmount((product.projected_usage || 0) * 1.5, product.tiers))
                    : 0) ||
                DEFAULT_BILLING_LIMIT
        )
    }, [customLimitUsd])

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        700: 'medium',
    })

    const freeTier = (billing?.has_active_subscription ? product.tiers?.[0]?.up_to : product.free_allocation) || 0

    const billingGaugeItems: BillingGaugeProps['items'] = useMemo(
        () =>
            [
                {
                    tooltip: (
                        <>
                            <b>Free tier limit</b>
                        </>
                    ),
                    color: 'success-light',
                    value: freeTier,
                    top: true,
                },
                {
                    tooltip: (
                        <>
                            <b>Current</b>
                        </>
                    ),
                    color: product.percentage_usage <= 1 ? 'success' : 'danger',
                    value: product.current_usage || 0,
                    top: false,
                },
                product.projected_usage && product.projected_usage > (product.current_usage || 0)
                    ? {
                          tooltip: (
                              <>
                                  <b>Projected</b>
                              </>
                          ),
                          color: 'border',
                          value: product.projected_usage || 0,
                          top: false,
                      }
                    : undefined,
                billingLimitAsUsage
                    ? {
                          tooltip: (
                              <>
                                  <b>Billing limit</b>
                              </>
                          ),
                          color: 'primary-alt-light',
                          top: true,
                          value: billingLimitAsUsage || 0,
                      }
                    : (undefined as any),
            ].filter(Boolean),
        [product, billingLimitAsUsage, customLimitUsd]
    )

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
                                        {billing?.billing_period?.interval}-to-date
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
                        <div className="pl-12 pb-8">
                            {/* TODO: We actually want to show this table regardless if there is an active sub */}
                            {billing?.has_active_subscription && (
                                <>
                                    {product.tiered && tableTierData ? (
                                        <LemonTable
                                            bordered={false}
                                            size="xs"
                                            uppercaseHeader={false}
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
                                            bordered={false}
                                            size="xs"
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
                </div>
                {billing?.billing_period?.interval == 'month' && (customLimitUsd || isEditingBillingLimit) && (
                    <div className="border-t border-border p-8">
                        <div className="flex">
                            <div className="flex items-center gap-1">
                                {!isEditingBillingLimit ? (
                                    <>
                                        <div
                                            className={clsx('cursor-pointer', customLimitUsd && 'text-primary')}
                                            onClick={() => setIsEditingBillingLimit(true)}
                                        >
                                            ${customLimitUsd}
                                        </div>
                                        <Tooltip
                                            title={
                                                <>
                                                    Set a billing limit to control your recurring costs. Some features
                                                    may stop working if your usage exceeds your billing cap.
                                                </>
                                            }
                                        >
                                            {billing?.billing_period?.interval}ly billing limit
                                        </Tooltip>
                                    </>
                                ) : (
                                    <>
                                        <div className="max-w-40">
                                            <LemonInput
                                                type="number"
                                                fullWidth={false}
                                                value={billingLimitInput}
                                                onChange={setBillingLimitInput}
                                                prefix={<b>$</b>}
                                                disabled={billingLoading}
                                                min={0}
                                                step={10}
                                                suffix={<>/month</>}
                                                size="small"
                                            />
                                        </div>

                                        <LemonButton
                                            onClick={() => updateBillingLimit(billingLimitInput)}
                                            loading={billingLoading}
                                            type="primary"
                                            size="small"
                                        >
                                            Save
                                        </LemonButton>
                                        <LemonButton
                                            onClick={() => setIsEditingBillingLimit(false)}
                                            disabled={billingLoading}
                                            type="secondary"
                                            size="small"
                                        >
                                            Cancel
                                        </LemonButton>
                                        {customLimitUsd ? (
                                            <LemonButton
                                                // icon={<IconDelete />}
                                                status="danger"
                                                size="small"
                                                tooltip="Remove billing limit"
                                                onClick={() => updateBillingLimit(undefined)}
                                            >
                                                Remove limit
                                            </LemonButton>
                                        ) : null}
                                    </>
                                )}
                            </div>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
