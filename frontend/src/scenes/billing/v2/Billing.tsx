import { useEffect, useMemo, useState } from 'react'
import { PageHeader } from 'lib/components/PageHeader'
import { billingLogic } from './billingLogic'
import {
    LemonButton,
    LemonDivider,
    LemonInput,
    LemonSelect,
    LemonSelectOptions,
    LemonSwitch,
    Link,
} from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { Spinner, SpinnerOverlay } from 'lib/components/Spinner/Spinner'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { AlertMessage } from 'lib/components/AlertMessage'
import { LemonDialog } from 'lib/components/LemonDialog'
import { BillingProductV2Type } from '~/types'
import { LemonLabel } from 'lib/components/LemonLabel/LemonLabel'
import { dayjs } from 'lib/dayjs'
import clsx from 'clsx'
import { BillingGauge, BillingGaugeProps } from './BillingGauge'
import { convertAmountToUsage, convertUsageToAmount, summarizeUsage } from './billing-utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'

export function BillingV2(): JSX.Element {
    const { billing, billingLoading, isActivateLicenseSubmitting, showLicenseDirectInput } = useValues(billingLogic)
    const { setShowLicenseDirectInput } = useActions(billingLogic)
    const { preflight } = useValues(preflightLogic)
    const [enterprisePackage, setEnterprisePackage] = useState(false)

    if (!billing && billingLoading) {
        return <SpinnerOverlay />
    }

    const supportLink = (
        <Link
            target="blank"
            to="https://posthog.com/support?utm_medium=in-product&utm_campaign=billing-service-unreachable"
        >
            {' '}
            contact support{' '}
        </Link>
    )

    const products =
        enterprisePackage && billing?.products_enterprise ? billing?.products_enterprise : billing?.products

    return (
        <div>
            <PageHeader title="Billing &amp; usage" />

            {!billing && !billingLoading ? (
                <div className="space-y-4">
                    <AlertMessage type="error">
                        There was an issue retrieving your current billing information. If this message persists please
                        {supportLink}.
                    </AlertMessage>

                    {!preflight?.cloud ? (
                        <AlertMessage type="info">
                            Please ensure your instance is able to reach <b>https://billing.posthog.com</b>
                            <br />
                            If this is not possible, please {supportLink} about licensing options for "air-gapped"
                            instances.
                        </AlertMessage>
                    ) : null}
                </div>
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
                                        Current bill total
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
                        {billing?.has_active_subscription ? (
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
                            <div className="space-y-4">
                                <LemonButton
                                    to={`/api/billing-v2/activation?plan=${
                                        enterprisePackage ? 'enterprise' : 'standard'
                                    }`}
                                    type="primary"
                                    size="large"
                                    fullWidth
                                    center
                                    disableClientSideRouting
                                >
                                    Setup payment
                                </LemonButton>

                                <div className="space-y-2">
                                    <div className="flex items-center justify-between">
                                        <LemonLabel>Enterprise package</LemonLabel>
                                        <LemonSwitch
                                            className="flex items-center justify-between"
                                            checked={enterprisePackage}
                                            onChange={setEnterprisePackage}
                                        />
                                    </div>
                                    <p>
                                        Starts at <b>$450/mo</b> and comes with SSO, advanced permissions, and a
                                        dedicated Slack channel for support
                                    </p>
                                </div>
                            </div>
                        )}

                        {!preflight?.cloud && billing?.license?.plan ? (
                            <div className="bg-primary-alt-highlight text-primary-alt rounded p-2 px-4">
                                <div className="text-center font-bold">
                                    {capitalizeFirstLetter(billing.license.plan)} license
                                </div>
                                <span>
                                    Please contact <a href="mailto:sales@posthog.com">sales@posthog.com</a> if you would
                                    like to make any changes to your license.
                                </span>
                            </div>
                        ) : null}

                        {!preflight?.cloud && !billing?.has_active_subscription ? (
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

            {products?.map((x) => (
                <div key={x.type}>
                    <LemonDivider dashed className="my-2" />
                    <BillingProduct product={x} />
                </div>
            ))}
        </div>
    )
}

const BillingProduct = ({ product }: { product: BillingProductV2Type }): JSX.Element => {
    const { billing, billingLoading } = useValues(billingLogic)
    const { updateBillingLimits } = useActions(billingLogic)

    const customLimitUsd = billing?.custom_limits_usd?.[product.type]

    const [tierAmountType, setTierAmountType] = useState<'individual' | 'total'>('individual')
    const [showBillingLimit, setShowBillingLimit] = useState(false)
    const [billingLimit, setBillingLimit] = useState<number | undefined>(100)
    const billingLimitInputChanged = parseInt(customLimitUsd || '-1') !== billingLimit
    const billingLimitAsUsage = showBillingLimit ? convertAmountToUsage(`${billingLimit}`, product.tiers) : 0

    const updateBillingLimit = (value: number | undefined): any => {
        const actuallyUpdateLimit = (): void => {
            updateBillingLimits({
                [product.type]: typeof value === 'number' ? `${value}` : null,
            })
        }
        if (value === undefined) {
            return actuallyUpdateLimit()
        }

        const newAmountAsUsage = convertAmountToUsage(`${value}`, product.tiers)

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
        setShowBillingLimit(!!customLimitUsd)
        setBillingLimit(
            parseInt(customLimitUsd || '0') ||
                parseInt(convertUsageToAmount((product.projected_usage || 0) * 1.5, product.tiers)) ||
                100
        )
    }, [customLimitUsd])

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        1000: 'medium',
    })

    const onBillingLimitToggle = (): void => {
        if (!showBillingLimit) {
            return setShowBillingLimit(true)
        }
        if (!customLimitUsd) {
            return setShowBillingLimit(false)
        }
        updateBillingLimit(undefined)
    }

    const billingGaugeItems: BillingGaugeProps['items'] = useMemo(
        () =>
            [
                {
                    tooltip: (
                        <>
                            <b>Free tier limit</b>
                            {!billing?.has_active_subscription ? <div>(With subscription)</div> : null}
                        </>
                    ),
                    color: billing?.has_active_subscription ? 'success-light' : 'success-highlight',
                    value: product.tiers?.[0]?.up_to || 0,
                    top: true,
                },
                !billing?.has_active_subscription
                    ? {
                          tooltip: (
                              <>
                                  <b>Free tier limit</b>
                                  <div>(Without subscription)</div>
                              </>
                          ),
                          color: 'success-light',
                          value: product.free_allocation,
                          top: true,
                      }
                    : (undefined as any),
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
        { label: `Per ${product.type.toLowerCase()}`, value: 'individual' },
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
            <div className="flex-1 py-4 pr-2 space-y-4">
                <div className="flex justify-between items-start">
                    <div>
                        <h3 className="font-bold">{product.name}</h3>
                        <p>{product.description}</p>
                    </div>
                </div>

                {product.current_amount_usd ? (
                    <div className="flex justify-between gap-8 flex-wrap">
                        <div className="space-y-2">
                            <LemonLabel info={'This is the current amount you have been billed for this month so far.'}>
                                Current bill
                            </LemonLabel>
                            <div className="font-bold text-4xl">${product.current_amount_usd}</div>
                        </div>
                        {product.tiered && (
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
                                        $
                                        {product.projected_usage
                                            ? convertUsageToAmount(product.projected_usage, product.tiers)
                                            : '0.00'}
                                    </div>
                                </div>
                                <div className="flex-1" />
                                <div className="space-y-2 text-right">
                                    <LemonLabel
                                        info={
                                            <>
                                                Set a billing limit to control your recurring costs.{' '}
                                                <b>
                                                    Your critical data will still be ingested and available in the
                                                    product
                                                </b>
                                                . Some features may cease operation if your usage greatly exceeds your
                                                billing cap.
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

                            <LemonSelect
                                size="small"
                                value={tierAmountType}
                                options={tierDisplayOptions}
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
                                            ? `${summarizeUsage(product.tiers[i - 1].up_to)} - ${summarizeUsage(
                                                  tier.up_to
                                              )}`
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
                    </>
                ) : (
                    <div className="space-y-2">
                        <div className="font-bold">Pricing breakdown</div>

                        <div className="flex justify-between py-2">
                            <span>Per month</span>
                            <span className="font-bold">${product.unit_amount_usd}</span>
                        </div>
                    </div>
                )}
            </div>
        </div>
    )
}
