import { LemonSelectOptions, LemonLabel, LemonButton, LemonInput, LemonDivider, LemonSelect } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useValues, useActions } from 'kea'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import { IconEdit, IconDelete } from 'lib/lemon-ui/icons'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { useState, useEffect, useMemo } from 'react'
import { BillingProductV2Type } from '~/types'
import { convertAmountToUsage, convertUsageToAmount, summarizeUsage } from './billing-utils'
import { BillingGaugeProps, BillingGauge } from './BillingGauge'
import { billingLogic } from './billingLogic'

const DEFAULT_BILLING_LIMIT = 500

const BillingProduct = ({ product }: { product: BillingProductV2Type }): JSX.Element | null => {
    const { billing, billingLoading } = useValues(billingLogic)
    const { updateBillingLimits } = useActions(billingLogic)
    const [tierAmountType, setTierAmountType] = useState<'individual' | 'total'>('individual')

    // The actual stored billing limit
    const customLimitUsd = billing?.custom_limits_usd?.[product.type]
    const [isEditingBillingLimit, setIsEditingBillingLimit] = useState(false)
    const [billingLimitInput, setBillingLimitInput] = useState<number | undefined>(DEFAULT_BILLING_LIMIT)

    const billingLimitAsUsage = product.tiers
        ? isEditingBillingLimit
            ? convertAmountToUsage(`${billingLimitInput}`, product.tiers)
            : convertAmountToUsage(customLimitUsd || '', product.tiers)
        : 0

    const usageKey = product.usage_key ?? product.type ?? ''
    const productType = { plural: usageKey, singular: usageKey.slice(0, -1) }

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

    const freeTier =
        (billing?.has_active_subscription
            ? product.tiers?.[0]?.unit_amount_usd === '0'
                ? product.tiers?.[0]?.up_to
                : 0
            : product.free_allocation) || 0

    const billingGaugeItems: BillingGaugeProps['items'] = useMemo(() => {
        return [
            freeTier
                ? {
                      tooltip: (
                          <>
                              <b>Free tier limit</b>
                          </>
                      ),
                      color: 'success-light',
                      value: freeTier,
                      top: true,
                  }
                : undefined,
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
        ].filter(Boolean)
    }, [product, billingLimitAsUsage, customLimitUsd])

    const tierDisplayOptions: LemonSelectOptions<string> = [
        { label: `Per ${productType.singular}`, value: 'individual' },
    ]

    if (billing?.has_active_subscription) {
        tierDisplayOptions.push({ label: `Current bill`, value: 'total' })
    }

    return (
        <div
            className={clsx('flex flex-wrap', {
                'flex-col pb-4': size === 'small',
            })}
            ref={ref}
        >
            <div className="flex-1 py-4 pr-2 ">
                <div className="flex gap-4 items-center pb-4">
                    {product.image_url ? (
                        <img className="w-10 h-10" alt="Logo for product" src={product.image_url} />
                    ) : null}
                    <div>
                        <h3 className="font-bold mb-0">{product.name}</h3>
                        <div>{product.description}</div>
                    </div>
                </div>

                {product.current_amount_usd ? (
                    <div className="flex justify-between gap-8 flex-wrap">
                        <div className="space-y-2">
                            <LemonLabel
                                info={`This is the current amount you have been billed for this ${billing?.billing_period?.interval} so far.`}
                            >
                                Current bill
                            </LemonLabel>
                            <div className="font-bold text-4xl">${product.current_amount_usd}</div>
                        </div>
                        {product.tiered && product.tiers && (
                            <>
                                <div className="space-y-2">
                                    <LemonLabel
                                        info={
                                            'This is roughly calculated based on your current bill and the remaining time left in this billing period.'
                                        }
                                    >
                                        Predicted bill
                                    </LemonLabel>
                                    <div className="font-bold text-muted text-2xl">
                                        ${product.projected_amount_usd || '0.00'}
                                    </div>
                                </div>
                                {billing?.billing_period?.interval == 'month' && (
                                    <div className="space-y-2">
                                        <LemonLabel
                                            info={
                                                <>
                                                    Set a billing limit to control your recurring costs.{' '}
                                                    <b>Data will be dropped after exceeding this limit</b>.
                                                </>
                                            }
                                        >
                                            Billing limit
                                        </LemonLabel>
                                        <div className="flex items-center gap-1">
                                            {!isEditingBillingLimit ? (
                                                <>
                                                    <div
                                                        className={clsx(
                                                            'text-muted font-semibold mr-2',
                                                            customLimitUsd && 'text-2xl'
                                                        )}
                                                    >
                                                        {customLimitUsd ? `$${customLimitUsd}` : 'No limit'}
                                                    </div>
                                                    <LemonButton
                                                        icon={<IconEdit />}
                                                        status="primary-alt"
                                                        size="small"
                                                        tooltip="Edit billing limit"
                                                        onClick={() => setIsEditingBillingLimit(true)}
                                                    />
                                                    {customLimitUsd ? (
                                                        <LemonButton
                                                            icon={<IconDelete />}
                                                            status="primary-alt"
                                                            size="small"
                                                            tooltip="Remove billing limit"
                                                            onClick={() => updateBillingLimit(undefined)}
                                                        />
                                                    ) : null}
                                                </>
                                            ) : (
                                                <>
                                                    <div style={{ maxWidth: 180 }}>
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
                                                        />
                                                    </div>

                                                    <LemonButton
                                                        onClick={() => setIsEditingBillingLimit(false)}
                                                        disabled={billingLoading}
                                                        type="secondary"
                                                    >
                                                        Cancel
                                                    </LemonButton>
                                                    <LemonButton
                                                        onClick={() => updateBillingLimit(billingLimitInput)}
                                                        loading={billingLoading}
                                                        type="primary"
                                                    >
                                                        Save
                                                    </LemonButton>
                                                </>
                                            )}
                                        </div>
                                    </div>
                                )}
                                <div className="flex-1" />
                            </>
                        )}
                    </div>
                ) : null}

                {product.tiered && <BillingGauge items={billingGaugeItems} />}

                {product.percentage_usage > 1 ? (
                    <AlertMessage type={'error'}>
                        You have exceeded the {customLimitUsd ? 'billing limit' : 'free tier limit'} for this product.
                    </AlertMessage>
                ) : null}
            </div>

            {size == 'medium' && <LemonDivider vertical dashed />}

            {billing?.has_active_subscription && (
                <div
                    className={clsx('space-y-2 text-xs', {
                        'p-4': size === 'medium',
                    })}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: size === 'medium' ? '20rem' : undefined }}
                >
                    {product.price_description ? (
                        <AlertMessage type="info">
                            <span dangerouslySetInnerHTML={{ __html: product.price_description }} />
                        </AlertMessage>
                    ) : null}

                    {product.tiered ? (
                        <>
                            <div className="flex justify-between items-center">
                                <b>Pricing breakdown</b>

                                {billing?.has_active_subscription ? (
                                    <LemonSelect
                                        size="small"
                                        value={tierAmountType}
                                        options={tierDisplayOptions}
                                        dropdownMatchSelectWidth={false}
                                        onChange={(val: any) => setTierAmountType(val)}
                                    />
                                ) : (
                                    <span className="font-semibold">Per {productType.singular}</span>
                                )}
                            </div>

                            <ul>
                                {product.tiers?.map((tier, i) => (
                                    <li
                                        key={i}
                                        className={clsx('flex justify-between py-2', {
                                            'border-t border-dashed': i > 0,
                                            'font-bold': tier.current_amount_usd !== null,
                                        })}
                                    >
                                        <span>
                                            {i === 0
                                                ? `First ${summarizeUsage(tier.up_to)} ${productType.plural} / ${
                                                      billing?.billing_period?.interval
                                                  }`
                                                : tier.up_to
                                                ? `${summarizeUsage(
                                                      product.tiers?.[i - 1].up_to || null
                                                  )} - ${summarizeUsage(tier.up_to)}`
                                                : `> ${summarizeUsage(product.tiers?.[i - 1].up_to || null)}`}
                                        </span>
                                        <b>
                                            {tierAmountType === 'individual' ? (
                                                <>
                                                    {tier.unit_amount_usd !== '0' ? `$${tier.unit_amount_usd}` : 'Free'}
                                                </>
                                            ) : (
                                                <>${tier.current_amount_usd || '0.00'}</>
                                            )}
                                        </b>
                                    </li>
                                ))}
                            </ul>
                        </>
                    ) : (
                        <div className="space-y-2">
                            <div className="font-bold">Pricing breakdown</div>

                            <div className="flex justify-between py-2">
                                <span>Per {billing.billing_period?.interval}</span>
                                <span className="font-bold">${product.unit_amount_usd}</span>
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}

export default BillingProduct
