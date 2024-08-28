import './Billing.scss'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { router } from 'kea-router'
import { SurprisedHog } from 'lib/components/hedgehogs'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { dayjs } from 'lib/dayjs'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { useEffect } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BillingCTAHero } from './BillingCTAHero'
import { billingLogic } from './billingLogic'
import { BillingProduct } from './BillingProduct'
import { UnsubscribeCard } from './UnsubscribeCard'
import { AnnualCreditModal } from './AnnualCreditModal'

export const scene: SceneExport = {
    component: Billing,
    logic: billingLogic,
}

export function Billing(): JSX.Element {
    const {
        billing,
        billingLoading,
        isOnboarding,
        showLicenseDirectInput,
        isActivateLicenseSubmitting,
        over20kAnnual,
        isAnnualPlan,
        billingError,
        selfServeCreditEligibility,
        isAnnualCreditModalOpen,
    } = useValues(billingLogic)
    const { reportBillingShown, showAnnualCreditModal } = useActions(billingLogic)
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
            {selfServeCreditEligibility.eligible && (
                <div className="mb-6">
                    <LemonBanner type="success" className="mb-2">
                        You are eligible for a self-serve annual credit.
                    </LemonBanner>
                    <LemonButton type="secondary" onClick={() => showAnnualCreditModal(true)}>
                        Apply for self-serve annual credit
                    </LemonButton>
                </div>
            )}
            {isAnnualCreditModalOpen && <AnnualCreditModal />}

            <div
                className={clsx('flex justify-between', {
                    'flex-col gap-4': size === 'small',
                    'flex-row': size !== 'small',
                })}
            >
                <div>
                    <div
                        className={clsx('flex flex-wrap gap-4 w-fit', {
                            'flex-col items-stretch': size === 'small',
                            'items-center': size !== 'small',
                        })}
                    >
                        {!isOnboarding && billing?.billing_period && (
                            <div className="flex-1 pt-2">
                                <div className="space-y-2">
                                    {billing?.has_active_subscription && (
                                        <>
                                            <LemonLabel
                                                info={`This is the current amount you have been billed for this ${billing.billing_period.interval} so far. This number updates once daily.`}
                                            >
                                                Current bill total
                                            </LemonLabel>
                                            <div className="font-bold text-6xl">
                                                ${billing.current_total_amount_usd_after_discount}
                                            </div>
                                            {billing.discount_percent && (
                                                <div>
                                                    <p className="ml-0">
                                                        <strong>{billing.discount_percent}%</strong> off discount
                                                        applied
                                                    </p>
                                                </div>
                                            )}
                                            {billing.discount_amount_usd && (
                                                <div>
                                                    <p className="ml-0">
                                                        <Tooltip
                                                            title={
                                                                billing?.amount_off_expires_at
                                                                    ? `Expires on ${billing?.amount_off_expires_at?.format(
                                                                          'LL'
                                                                      )}`
                                                                    : null
                                                            }
                                                            placement="bottom-start"
                                                        >
                                                            <strong>
                                                                $
                                                                {parseInt(billing.discount_amount_usd).toLocaleString()}
                                                            </strong>
                                                        </Tooltip>{' '}
                                                        remaining credits applied to your bill.
                                                    </p>
                                                </div>
                                            )}
                                        </>
                                    )}
                                    <div>
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
                        <div className="w-fit mt-2">
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
                {!isOnboarding && !isAnnualPlan && over20kAnnual && (
                    <div className="bg-[var(--glass-bg-3000)] flex flex-row gap-2 relative pl-6 p-4 border rounded min-w-120 w-fit">
                        <div className="flex flex-col pl-2 ">
                            <h3>You've unlocked enterprise-grade perks:</h3>
                            <ul className="pl-4">
                                <li className="flex gap-2 items-center">
                                    <IconCheckCircle className="text-success shrink-0" />
                                    <span>
                                        <strong>Save 20%</strong> by switching to up-front annual billing
                                    </span>
                                </li>
                                <li className="flex gap-2 items-center">
                                    <IconCheckCircle className="text-success shrink-0" />
                                    <span>
                                        Get <strong>discounts on bundled subscriptions</strong> to multiple products
                                    </span>
                                </li>
                                <li className="flex gap-2 items-center">
                                    <IconCheckCircle className="text-success shrink-0" />
                                    <span>
                                        Get <strong>customized training</strong> for you and your team
                                    </span>
                                </li>
                                <li className="flex gap-2 items-center">
                                    <IconCheckCircle className="text-success shrink-0" />
                                    <span>
                                        Get dedicated support via <strong>private Slack channel</strong>
                                    </span>
                                </li>
                                <li className="flex gap-2 items-center">
                                    <IconCheckCircle className="text-success shrink-0" />
                                    <span>
                                        We'll even send you <strong>awesome free merch</strong>
                                    </span>
                                </li>
                            </ul>
                            <div className="pt-1 self-start flex flex-row gap-1 mt-2">
                                <LemonButton type="secondary" to="mailto:sales@posthog.com">
                                    Let's chat
                                </LemonButton>
                            </div>
                        </div>
                        <div className="h-24 self-end -scale-x-100 -ml-20 -mb-2">
                            <SurprisedHog className="max-h-full w-auto object-contain" />
                        </div>
                    </div>
                )}
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
