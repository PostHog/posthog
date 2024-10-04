import './Billing.scss'

import { LemonButton, LemonDivider, LemonInput, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { router } from 'kea-router'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { dayjs } from 'lib/dayjs'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { humanFriendlyCurrency } from 'lib/utils'
import { useEffect } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BillingCTAHero } from './BillingCTAHero'
import { billingLogic } from './billingLogic'
import { BillingProduct } from './BillingProduct'
import { CreditCTAHero } from './CreditCTAHero'
import { UnsubscribeCard } from './UnsubscribeCard'

export const scene: SceneExport = {
    component: Billing,
    logic: billingLogic,
}

export function Billing(): JSX.Element {
    const { billing, billingLoading, isOnboarding, showLicenseDirectInput, isActivateLicenseSubmitting, billingError } =
        useValues(billingLogic)
    const { reportBillingShown } = useActions(billingLogic)
    const { preflight, isCloudOrDev } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)

    if (preflight && !isCloudOrDev) {
        router.actions.push(urls.default())
    }

    useEffect(() => {
        if (billing) {
            reportBillingShown()
        }
    }, [!!billing])

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        1000: 'medium',
    })

    if (!billing && billingLoading) {
        return (
            <>
                <SpinnerOverlay sceneLevel />
            </>
        )
    }

    if (!billing && !billingLoading) {
        return (
            <div className="space-y-4">
                <LemonBanner type="error">
                    {
                        'There was an issue retrieving your current billing information. If this message persists, please '
                    }
                    {preflight?.cloud ? (
                        <Link onClick={() => openSupportForm({ kind: 'bug', target_area: 'billing' })}>
                            submit a bug report
                        </Link>
                    ) : (
                        <Link to="mailto:sales@posthog.com">contact sales@posthog.com</Link>
                    )}
                    .
                </LemonBanner>
            </div>
        )
    }

    const products = billing?.products
    const platformAndSupportProduct = products?.find((product) => product.type === 'platform_and_support')
    return (
        <div ref={ref}>
            {showLicenseDirectInput && (
                <>
                    <Form logic={billingLogic} formKey="activateLicense" enableFormOnSubmit className="space-y-4">
                        <Field name="license" label="Activate license key">
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
            )}

            {billingError && (
                <LemonBanner type={billingError.status} className="mb-2" action={billingError.action}>
                    {billingError.message}
                </LemonBanner>
            )}

            {billing?.free_trial_until ? (
                <LemonBanner type="success" className="mb-2">
                    You are currently on a free trial until <b>{billing.free_trial_until.format('LL')}</b>
                </LemonBanner>
            ) : null}

            {!billing?.has_active_subscription && platformAndSupportProduct && (
                <div className="mb-6">
                    <BillingCTAHero product={platformAndSupportProduct} />
                </div>
            )}

            <CreditCTAHero />

            <div
                className={clsx('flex justify-between', {
                    'flex-col gap-4': size === 'small',
                    'flex-row': size !== 'small',
                })}
            >
                <div>
                    <div
                        className={clsx('flex flex-wrap gap-6 w-fit', {
                            'flex-col items-stretch': size === 'small',
                            'items-center': size !== 'small',
                        })}
                    >
                        {!isOnboarding && billing?.billing_period && (
                            <div className="flex-1 pt-2">
                                <div className="space-y-4">
                                    {billing?.has_active_subscription && (
                                        <>
                                            <div className="flex flex-row gap-10 items-end">
                                                <div>
                                                    <LemonLabel
                                                        info={`This is the current amount you have been billed for this ${billing.billing_period.interval} so far. This number updates once daily.`}
                                                    >
                                                        Current bill total
                                                    </LemonLabel>
                                                    <div className="font-bold text-6xl">
                                                        {billing.discount_percent
                                                            ? // if they have a discount percent, we want to show the amount they are due - so the total after discount
                                                              humanFriendlyCurrency(
                                                                  billing.current_total_amount_usd_after_discount
                                                              )
                                                            : // but if they have credits, we want to show the amount they are due before credits,
                                                              // so they know what their total deduction will be
                                                              // We don't let people have credits and discounts at the same time
                                                              humanFriendlyCurrency(billing.current_total_amount_usd)}
                                                    </div>
                                                </div>
                                                {billing?.discount_amount_usd && (
                                                    <div>
                                                        <LemonLabel
                                                            info={`The total credits remaining in your account. ${
                                                                billing?.amount_off_expires_at
                                                                    ? 'Your credits expire on ' +
                                                                      billing?.amount_off_expires_at?.format('LL')
                                                                    : null
                                                            }`}
                                                            className="text-muted"
                                                        >
                                                            Available credits
                                                        </LemonLabel>
                                                        <div className="font-semibold text-2xl text-muted">
                                                            {humanFriendlyCurrency(billing?.discount_amount_usd, 0)}
                                                        </div>
                                                    </div>
                                                )}
                                                {billing?.discount_percent && (
                                                    <div>
                                                        <LemonLabel
                                                            info="The discount applied to your current bill, reflected in the total amount."
                                                            className="text-muted"
                                                        >
                                                            Applied discount
                                                        </LemonLabel>
                                                        <div className="font-semibold text-2xl text-muted">
                                                            {billing.discount_percent}%
                                                        </div>
                                                    </div>
                                                )}
                                            </div>
                                        </>
                                    )}
                                    <div className="my-4">
                                        <p className="ml-0 mb-0">
                                            {billing?.has_active_subscription ? 'Billing period' : 'Cycle'}:{' '}
                                            <b>{billing.billing_period.current_period_start.format('LL')}</b> to{' '}
                                            <b>{billing.billing_period.current_period_end.format('LL')}</b> (
                                            {billing.billing_period.current_period_end.diff(dayjs(), 'days')} days
                                            remaining)
                                        </p>
                                        {!billing.has_active_subscription && (
                                            <p className="italic ml-0 text-muted">
                                                Monthly free allocation resets at the end of the cycle.
                                            </p>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>

                    {!isOnboarding && billing?.has_active_subscription && (
                        <div className="w-fit mt-4">
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                to={billing.stripe_portal_url}
                                disableClientSideRouting
                                targetBlank
                                center
                                data-attr="manage-billing"
                            >
                                Manage card details and view past invoices
                            </LemonButton>
                        </div>
                    )}
                </div>
            </div>

            <LemonDivider className="mt-6 mb-8" />

            <div className="flex justify-between mt-4">
                <h2>Products</h2>
            </div>

            {products
                ?.filter((product) => !product.inclusion_only || product.plans.some((plan) => !plan.included_if))
                ?.map((x) => (
                    <div key={x.type}>
                        <BillingProduct product={x} />
                    </div>
                ))}
            <div>
                {billing?.subscription_level == 'paid' && !!platformAndSupportProduct ? (
                    <>
                        <LemonDivider />
                        <UnsubscribeCard product={platformAndSupportProduct} />
                    </>
                ) : null}
            </div>
        </div>
    )
}
