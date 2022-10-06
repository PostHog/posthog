import React, { useEffect, useMemo, useState } from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { billingLogic } from './billingLogic'
import { LemonButton, LemonDivider, LemonInput, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Spinner, SpinnerOverlay } from 'lib/components/Spinner/Spinner'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { AlertMessage } from 'lib/components/AlertMessage'
import { LemonDialog } from 'lib/components/LemonDialog'
import { BillingProductV2Type, BillingV2Type } from '~/types'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { dayjs } from 'lib/dayjs'
import clsx from 'clsx'
import { BillingGuage, BillingGuageProps } from './BillingGuage'
import { convertAmountToUsage, convertUsageToAmount, projectUsage, summarizeUsage } from './billing-utils'

export function BillingV2(): JSX.Element {
    const { billing, billingLoading, isActivateLicenseSubmitting, showLicenseDirectInput } = useValues(billingLogic)
    const { setShowLicenseDirectInput } = useActions(billingLogic)

    if (!billing && billingLoading) {
        return <SpinnerOverlay />
    }

    return (
        <div>
            <PageHeader title="Billing &amp; usage" />

            {!billing && !billingLoading ? (
                <AlertMessage type="error">
                    There was an issue retreiving your current billing information. If this message persists please
                    contact support.
                </AlertMessage>
            ) : (
                <div className="flex">
                    <div className="flex-1">
                        {billing?.billing_period ? (
                            <>
                                <p>
                                    Your current billing period is from{' '}
                                    <b>{billing.billing_period.current_period_start.format('LL')}</b> to{' '}
                                    <b>{billing.billing_period.current_period_end.format('LL')}</b>
                                </p>

                                <div className="space-y-2">
                                    <LemonLabel
                                        info={'This is the current amount you have been billed for this month so far.'}
                                    >
                                        Current bill
                                    </LemonLabel>
                                    <div className="font-bold text-4xl">${billing.current_total_amount_usd}</div>
                                </div>
                                <p>
                                    <b>{billing.billing_period.current_period_end.diff(dayjs(), 'days')} days</b>{' '}
                                    remaining in your billing period.
                                </p>
                            </>
                        ) : (
                            <>
                                <h2 className="font-bold">
                                    Unlock a massive free tier simply by setting up your billing
                                </h2>
                                <p>
                                    Simply set up your payment details to unlock a massive free allocation of events and
                                    recordings <b>every month!</b> Once setup, you can configure your billing limits to
                                    ensure you are never billed for more than you need.
                                </p>
                            </>
                        )}
                    </div>

                    <LemonDivider vertical dashed />

                    <div className="p-4 space-y-2" style={{ width: '20rem' }}>
                        {billing?.stripe_portal_url ? (
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                to={billing.stripe_portal_url}
                                disableClientSideRouting
                                fullWidth
                                center
                            >
                                Manage subscription
                            </LemonButton>
                        ) : showLicenseDirectInput ? (
                            <>
                                <Form
                                    logic={billingLogic}
                                    formKey="activateLicense"
                                    enableFormOnSubmit
                                    className="space-y-4"
                                >
                                    <Field name="license" label={'Activate license key'}>
                                        <LemonInput fullWidth autoFocus />
                                    </Field>

                                    <LemonButton
                                        type="primary"
                                        htmlType="submit"
                                        loading={isActivateLicenseSubmitting}
                                        fullWidth
                                        center
                                    >
                                        Activate license key
                                    </LemonButton>
                                </Form>
                            </>
                        ) : (
                            <>
                                <LemonButton
                                    to="/api/billing-v2/activation"
                                    type="primary"
                                    size="large"
                                    fullWidth
                                    center
                                    disableClientSideRouting
                                >
                                    Setup payment
                                </LemonButton>
                            </>
                        )}

                        {!billing?.stripe_portal_url ? (
                            <LemonButton
                                fullWidth
                                center
                                onClick={() => setShowLicenseDirectInput(!showLicenseDirectInput)}
                            >
                                {!showLicenseDirectInput
                                    ? 'I already have a license key'
                                    : "I don't have a license key"}
                            </LemonButton>
                        ) : null}
                    </div>
                </div>
            )}

            {billing?.products?.map((x) => (
                <>
                    <LemonDivider dashed className="my-2" />
                    <BillingProduct
                        product={x}
                        billingPeriod={billing.billing_period}
                        customLimitUsd={billing.custom_limits_usd?.[x.type]}
                    />
                </>
            ))}
        </div>
    )
}

const BillingProduct = ({
    product,
    billingPeriod,
    customLimitUsd,
}: {
    product: BillingProductV2Type
    billingPeriod?: BillingV2Type['billing_period']
    customLimitUsd?: string | null
}): JSX.Element => {
    const { billing, billingLoading } = useValues(billingLogic)
    const { updateBillingLimits } = useActions(billingLogic)
    const [tierAmountType, setTierAmountType] = useState<'individual' | 'total'>('individual')
    const [showBillingLimit, setShowBillingLimit] = useState(false)
    const [billingLimit, setBillingLimit] = useState<number | undefined>(100)
    const billingLimitInputChanged = parseInt(customLimitUsd || '-1') !== billingLimit
    const billingLimitAsUsage = showBillingLimit ? convertAmountToUsage(`${billingLimit}`, product.tiers) : 0
    const projectedUsage = projectUsage(product.current_usage, billingPeriod)

    const updateBillingLimit = (value: number | undefined): any => {
        updateBillingLimits({
            [product.type]: typeof value === 'number' ? `${value}` : null,
        })
    }

    useEffect(() => {
        setShowBillingLimit(!!customLimitUsd)
        setBillingLimit(
            parseInt(customLimitUsd || '0') ||
                parseInt(convertUsageToAmount((projectedUsage || 0) * 1.5, product.tiers)) ||
                100
        )
    }, [customLimitUsd])

    const onBillingLimitToggle = (): void => {
        if (!showBillingLimit) {
            return setShowBillingLimit(true)
        }
        if (!customLimitUsd) {
            return setShowBillingLimit(false)
        }
        LemonDialog.open({
            title: 'Remove billing limit',
            description:
                'Your predicted usage is above your current billing limit which is likely to result in a bill. Are you sure you want to remove the limit?',
            primaryButton: {
                children: 'Yes, remove the limit',
                onClick: () => updateBillingLimit(undefined),
            },
            secondaryButton: {
                children: 'I changed my mind',
            },
        })
    }

    const billingGuageItems: BillingGuageProps['items'] = useMemo(
        () =>
            [
                {
                    tooltip: (
                        <>
                            <b>Free tier limit</b>
                            {!billing?.stripe_portal_url ? <div>With subscription</div> : null}
                        </>
                    ),
                    color: billing?.stripe_portal_url ? 'success-light' : 'danger-light',
                    value: product.tiers?.[0]?.up_to || 0,
                    top: true,
                    // Background
                },
                !billing?.stripe_portal_url
                    ? {
                          tooltip: (
                              <>
                                  <b>Free tier limit</b>
                                  <div>Without subscription</div>
                              </>
                          ),
                          color: 'success-light',
                          value: product.free_allocation,
                          top: true,
                          // Background
                      }
                    : (undefined as any),
                {
                    tooltip: (
                        <>
                            <b>Current</b>
                        </>
                    ),
                    color: 'success',
                    value: product.current_usage || 0,
                    top: false,
                    // Foreground
                },
                projectedUsage && projectedUsage > (product.current_usage || 0)
                    ? {
                          tooltip: (
                              <>
                                  <b>Projected</b>
                              </>
                          ),
                          color: 'border',
                          value: projectedUsage || 0,
                          top: false,
                          // Background
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
        [product, billingLimitAsUsage]
    )

    return (
        <div className="flex">
            <div className="flex-1 py-4 pr-2 space-y-4">
                <div className="flex justify-between items-start">
                    <div>
                        <h3 className="font-bold">{product.name}</h3>
                        <p>{product.description}</p>
                    </div>
                </div>

                {product.current_amount_usd ? (
                    <div className="flex justify-between gap-8">
                        <div className="space-y-2">
                            <LemonLabel info={'This is the current amount you have been billed for this month so far.'}>
                                Current bill
                            </LemonLabel>
                            <div className="font-bold text-4xl">${product.current_amount_usd}</div>
                        </div>
                        <div className="space-y-2">
                            <LemonLabel
                                info={
                                    'This is roughly caculated based on your current bill and the remaining time left in this billing period.'
                                }
                            >
                                Predicted bill
                            </LemonLabel>
                            <div className="font-bold text-muted text-2xl">
                                ${projectedUsage ? convertUsageToAmount(projectedUsage, product.tiers) : '0.00'}
                            </div>
                        </div>
                        <div className="flex-1" />
                        <div className="space-y-2 text-right">
                            <LemonLabel
                                info={
                                    <>
                                        Set a billing limit to control your recurring costs.{' '}
                                        <b>Your critical data will still be ingested and available in the product</b>.
                                        Some features may cease operation if your usage greatly exceeds your billing
                                        cap.
                                    </>
                                }
                            >
                                Billing limit
                            </LemonLabel>
                            <div className="flex justify-end gap-2 items-center">
                                {showBillingLimit ? (
                                    <div style={{ maxWidth: 180 }}>
                                        <LemonInput
                                            type="number"
                                            fullWidth={false}
                                            value={billingLimit}
                                            onChange={setBillingLimit}
                                            prefix={<b>$</b>}
                                            disabled={billingLoading}
                                            min={0}
                                            step={10}
                                            suffix={<>/month</>}
                                        />
                                    </div>
                                ) : (
                                    <span className="text-muted">No limit set</span>
                                )}

                                {showBillingLimit && billingLimitInputChanged ? (
                                    <LemonButton
                                        onClick={() => updateBillingLimit(billingLimit)}
                                        loading={billingLoading}
                                        type="secondary"
                                    >
                                        Save
                                    </LemonButton>
                                ) : billingLoading ? (
                                    <Spinner className="text-lg" />
                                ) : (
                                    <LemonSwitch
                                        className="my-2"
                                        checked={showBillingLimit}
                                        onChange={onBillingLimitToggle}
                                    />
                                )}
                            </div>
                        </div>
                    </div>
                ) : null}

                <BillingGuage items={billingGuageItems} />
            </div>

            <LemonDivider vertical dashed />

            <div className="p-4 space-y-2 text-xs" style={{ width: '20rem' }}>
                {product.price_description ? (
                    <AlertMessage type="info">
                        <span dangerouslySetInnerHTML={{ __html: product.price_description }} />
                    </AlertMessage>
                ) : null}
                <div className="flex justify-between items-center">
                    <b>Pricing breakdown</b>

                    <LemonSelect
                        size="small"
                        value={tierAmountType}
                        options={[
                            { label: `Per ${product.type.toLowerCase()}`, value: 'individual' },
                            { label: `Current bill`, value: 'total' },
                        ]}
                        dropdownMatchSelectWidth={false}
                        onChange={(val: any) => setTierAmountType(val)}
                    />
                </div>

                <ul>
                    {product.tiers.map((tier, i) => (
                        <li
                            key={i}
                            className={clsx('flex justify-between py-2', {
                                'border-t border-dashed': i > 0,
                                'font-bold': tier.current_amount_usd !== null,
                            })}
                        >
                            <span>
                                {i === 0
                                    ? `First ${summarizeUsage(tier.up_to)} ${product.type.toLowerCase()} / mo`
                                    : tier.up_to
                                    ? `${summarizeUsage(product.tiers[i - 1].up_to)} - ${summarizeUsage(tier.up_to)}`
                                    : `> ${summarizeUsage(product.tiers[i - 1].up_to)}`}
                            </span>
                            <b>
                                {tierAmountType === 'individual' ? (
                                    <>{tier.unit_amount_usd !== '0' ? `$${tier.unit_amount_usd}` : 'Free'}</>
                                ) : (
                                    <>${tier.current_amount_usd || '0.00'}</>
                                )}
                            </b>
                        </li>
                    ))}
                </ul>
            </div>
        </div>
    )
}
