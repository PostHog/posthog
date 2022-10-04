import React, { useEffect, useState } from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { billingLogic } from './billingLogic'
import { LemonButton, LemonDivider, LemonInput, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { AlertMessage } from 'lib/components/AlertMessage'
import { LemonDialog } from 'lib/components/LemonDialog'
import { BillingProductV2Type } from '~/types'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { dayjs } from 'lib/dayjs'

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
                        <p>Paying is good because money is good 👍</p>

                        {billing?.billing_period ? (
                            <>
                                <p>
                                    Your current billing period is from{' '}
                                    <b>{billing.billing_period.current_period_start.format('LL')}</b> to{' '}
                                    <b>{billing.billing_period.current_period_end.format('LL')}</b>
                                </p>
                                <p>
                                    <b>{billing.billing_period.current_period_end.diff(dayjs(), 'days')} days</b>{' '}
                                    remaining in your billing period.
                                </p>
                            </>
                        ) : null}
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
                    <BillingProduct product={x} customLimitUsd={billing.custom_limits_usd?.[x.type]} />
                </>
            ))}
        </div>
    )
}

const summarizeUsage = (usage: number | null): string => {
    if (usage === null) {
        return ''
    } else if (usage < 1000) {
        return `${usage} events`
    } else if (Math.round(usage / 1000) < 1000) {
        return `${Math.round(usage / 1000)} thousand`
    } else {
        return `${Math.round(usage / 1000000)} million`
    }
}

const BillingProduct = ({
    product,
    customLimitUsd,
}: {
    product: BillingProductV2Type
    customLimitUsd?: string | null
}): JSX.Element => {
    const { billingLoading } = useValues(billingLogic)
    const { updateBillingLimits } = useActions(billingLogic)

    const [showBillingLimit, setShowBillingLimit] = useState(false)
    const [billingLimit, setBillingLimit] = useState<number | undefined>(100)

    const updateBillingLimit = (value: number | undefined): any => {
        const parsedValue = typeof value === 'number' ? `${value}` : null

        updateBillingLimits({
            [product.type]: parsedValue,
        })
    }

    useEffect(() => {
        setShowBillingLimit(!!customLimitUsd)
        setBillingLimit(parseInt(customLimitUsd || '100'))
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

    const billingLimitInputChanged = parseInt(customLimitUsd || '-1') !== billingLimit

    return (
        <div className="flex">
            <div className="flex-1 py-4 pr-2 space-y-4">
                <div className="flex justify-between items-start">
                    <div>
                        <h3>{product.name}</h3>
                        <p>{product.description}</p>
                    </div>
                </div>

                <div className="flex justify-between gap-8 text-right">
                    {product.current_amount_usd ? (
                        <>
                            <div>
                                <LemonLabel
                                    info={'This is the current amount you have been billed for this month so far.'}
                                >
                                    Current bill
                                </LemonLabel>
                                <div className="font-bold text-4xl">${product.current_amount_usd}</div>
                            </div>
                            <div>
                                <LemonLabel
                                    info={
                                        'This is roughly caculated based on your current bill and the remaining time left in this billing period.'
                                    }
                                >
                                    Predicted bill
                                </LemonLabel>
                                <div className="font-bold text-muted text-2xl">
                                    ${parseFloat(product.current_amount_usd) * 100}
                                </div>
                            </div>
                        </>
                    ) : null}
                    <div className="flex-1" />
                    <div className="space-y-2">
                        <LemonLabel
                            info={`Billing limits can help you control the maximum you wish to pay in a given period. 
                                As you approach the billing limit you will be notified and given the option to increase it.
                                If you exceed the limit you will not be billed but you will be locked out from using certain areas of the product and incoming data may be lost.`}
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

                <div className="">
                    <div className="rounded-lg bg-border-light h-2">
                        <div className="rounded-lg bg-success h-2 w-1/3" />
                    </div>
                </div>

                {product.free_allocation}
                {product.current_usage}
                {product.usage_limit}
            </div>

            <LemonDivider vertical dashed />

            <div className="p-4 space-y-2 text-xs" style={{ width: '20rem' }}>
                <h4>Pricing breakdown</h4>
                <p>Pay per {product.type.toLowerCase()}</p>
                <ul>
                    {product.tiers.map((tier, i) => (
                        <li key={i} className="flex justify-between border-b border-dashed py-2">
                            <span>
                                {i === 0
                                    ? `First ${summarizeUsage(tier.up_to)} ${product.type.toLowerCase()} / mo`
                                    : tier.up_to
                                    ? `${summarizeUsage(product.tiers[i - 1].up_to)} - ${summarizeUsage(tier.up_to)}`
                                    : `> ${summarizeUsage(product.tiers[i - 1].up_to)}`}
                            </span>
                            <b>{tier.unit_amount_usd !== '0' ? `$${tier.unit_amount_usd}` : 'Free'}</b>
                        </li>
                    ))}
                </ul>
            </div>
        </div>
    )
}
