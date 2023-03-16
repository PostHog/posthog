import { useEffect, useMemo, useState } from 'react'
import { billingLogic } from './billingLogic'
import { LemonButton, LemonDivider, LemonInput, LemonSelect, LemonSelectOptions, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { BillingProductV2Type } from '~/types'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { dayjs } from 'lib/dayjs'
import clsx from 'clsx'
import { BillingGauge, BillingGaugeProps } from './BillingGauge'
import { convertAmountToUsage, convertUsageToAmount, summarizeUsage } from './billing-utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { IconDelete, IconEdit } from 'lib/lemon-ui/icons'
import { PlanTable } from './PlanTable'
import { BillingHero } from './BillingHero'
import { PageHeader } from 'lib/components/PageHeader'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'

const DEFAULT_BILLING_LIMIT = 500

export const scene: SceneExport = {
    component: Billing,
    logic: billingLogic,
}

export function BillingPageHeader(): JSX.Element {
    return <PageHeader title="Billing &amp; usage" />
}

export function Billing(): JSX.Element {
    const { billing, billingLoading, isActivateLicenseSubmitting, showLicenseDirectInput } = useValues(billingLogic)
    const { reportBillingV2Shown } = useActions(billingLogic)
    const { preflight } = useValues(preflightLogic)
    const cloudOrDev = preflight?.cloud || preflight?.is_debug

    useEffect(() => {
        if (billing) {
            reportBillingV2Shown()
        }
    }, [!!billing])

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        1000: 'medium',
    })

    if (!billing && billingLoading) {
        return (
            <>
                <BillingPageHeader />
                <SpinnerOverlay />
            </>
        )
    }

    if (!billing && !billingLoading) {
        const supportLink = (
            <Link
                target="blank"
                to="https://posthog.com/support?utm_medium=in-product&utm_campaign=billing-service-unreachable"
            >
                {' '}
                contact support{' '}
            </Link>
        )
        return (
            <div className="space-y-4">
                <BillingPageHeader />
                <AlertMessage type="error">
                    There was an issue retrieving your current billing information. If this message persists please
                    {supportLink}.
                </AlertMessage>

                {!cloudOrDev ? (
                    <AlertMessage type="info">
                        Please ensure your instance is able to reach <b>https://billing.posthog.com</b>
                        <br />
                        If this is not possible, please {supportLink} about licensing options for "air-gapped"
                        instances.
                    </AlertMessage>
                ) : null}
            </div>
        )
    }

    const products = billing?.products

    return (
        <div ref={ref}>
            <BillingPageHeader />
            {billing?.free_trial_until ? (
                <AlertMessage type="success" className="mb-2">
                    You are currently on a free trial until <b>{billing.free_trial_until.format('LL')}</b>
                </AlertMessage>
            ) : null}
            {!billing?.has_active_subscription && cloudOrDev && (
                <>
                    <div className="my-8">
                        <BillingHero />
                    </div>
                    <div className="mb-18 flex justify-center">
                        <PlanTable
                            redirectPath={
                                router.values.location.pathname.includes('/ingestion')
                                    ? urls.ingestion() + '/billing'
                                    : ''
                            }
                        />
                    </div>
                </>
            )}
            <div
                className={clsx('flex flex-wrap gap-4', {
                    'flex-col pb-4 items-stretch': size === 'small',
                    'items-center': size !== 'small',
                })}
            >
                <div className="flex-1">
                    {billing?.billing_period ? (
                        <div className="space-y-2">
                            <p>
                                Your current {billing?.has_active_subscription ? 'billing period' : 'cycle'} is from{' '}
                                <b>{billing.billing_period.current_period_start.format('LL')}</b> to{' '}
                                <b>{billing.billing_period.current_period_end.format('LL')}</b>
                            </p>

                            {billing?.has_active_subscription && (
                                <>
                                    <LemonLabel
                                        info={`This is the current amount you have been billed for this ${billing.billing_period.interval} so far.`}
                                    >
                                        Current bill total
                                    </LemonLabel>
                                    <div className="font-bold text-6xl">
                                        ${billing.current_total_amount_usd_after_discount}
                                    </div>
                                    {billing.discount_percent && (
                                        <div className="text-xl">
                                            ({billing.discount_percent}% off discount applied)
                                        </div>
                                    )}
                                    {billing.discount_amount_usd && (
                                        <div className="text-xl">
                                            (-${billing.discount_amount_usd} discount applied)
                                        </div>
                                    )}
                                </>
                            )}

                            <p>
                                <b>{billing.billing_period.current_period_end.diff(dayjs(), 'days')} days</b> remaining
                                in your{' '}
                                {billing?.has_active_subscription
                                    ? 'billing period.'
                                    : 'cycle. Your free allocation will reset at the end of the cycle.'}
                            </p>
                        </div>
                    ) : (
                        <>
                            <div>
                                <h1 className="font-bold">Current usage</h1>
                            </div>
                        </>
                    )}
                </div>

                <div
                    className={clsx('space-y-2', {
                        'p-4': size === 'medium',
                    })}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: size === 'medium' ? '20rem' : undefined }}
                >
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
                    ) : null}
                    {!cloudOrDev && billing?.license?.plan ? (
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

                    {!cloudOrDev && !billing?.has_active_subscription ? (
                        <p>
                            Self-hosted licenses are no longer available for purchase. Please contact{' '}
                            <a href="mailto:sales@posthog.com">sales@posthog.com</a> to discuss options.
                        </p>
                    ) : null}
                </div>
            </div>

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
                                        $
                                        {product.projected_usage
                                            ? convertUsageToAmount(product.projected_usage, product.tiers)
                                            : '0.00'}
                                    </div>
                                </div>
                                {billing?.billing_period?.interval == 'month' && (
                                    <div className="space-y-2">
                                        <LemonLabel
                                            info={
                                                <>
                                                    Set a billing limit to control your recurring costs.{' '}
                                                    <b>
                                                        Your critical data will still be ingested and available in the
                                                        product
                                                    </b>
                                                    . Some features may stop working if your usage greatly exceeds your
                                                    billing cap.
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
