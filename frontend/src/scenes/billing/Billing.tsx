import './Billing.scss'

import { LemonButton, LemonDivider, LemonInput, Link } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { router } from 'kea-router'
import { JudgeHog } from 'lib/components/hedgehogs'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { OrganizationMembershipLevel } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { toSentenceCase } from 'lib/utils'
import { useEffect } from 'react'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BillingPlanType, BillingProductV2Type, ProductKey } from '~/types'

import { BillingHero } from './BillingHero'
import { billingLogic } from './billingLogic'
import { BillingProduct } from './BillingProduct'
import { BillingSummary } from './BillingSummary'
import { CreditCTAHero } from './CreditCTAHero'
import { StripePortalButton } from './StripePortalButton'
import { UnsubscribeCard } from './UnsubscribeCard'

export const scene: SceneExport = {
    component: Billing,
    logic: billingLogic,
}

export function Billing(): JSX.Element {
    const {
        billing,
        billingLoading,
        showLicenseDirectInput,
        isActivateLicenseSubmitting,
        billingError,
        showBillingSummary,
        showCreditCTAHero,
        showBillingHero,
    } = useValues(billingLogic)
    const { reportBillingShown } = useActions(billingLogic)
    const { preflight, isCloudOrDev } = useValues(preflightLogic)
    const { openSupportForm } = useActions(supportLogic)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

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
        768: 'medium',
    })

    if (!billing && billingLoading) {
        return (
            <>
                <SpinnerOverlay sceneLevel />
            </>
        )
    }

    if (restrictionReason) {
        return (
            <div className="deprecated-space-y-4">
                <h1>Billing</h1>
                <LemonBanner type="warning">{restrictionReason}</LemonBanner>
                <div className="flex">
                    <LemonButton type="primary" to={urls.default()}>
                        Go back home
                    </LemonButton>
                </div>
            </div>
        )
    }

    if (!billing && !billingLoading) {
        return (
            <div className="deprecated-space-y-4">
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
    const platformAndSupportProduct = products?.find((product) => product.type === ProductKey.PLATFORM_AND_SUPPORT)
    return (
        <div ref={ref}>
            {showLicenseDirectInput && (
                <>
                    <Form
                        logic={billingLogic}
                        formKey="activateLicense"
                        enableFormOnSubmit
                        className="deprecated-space-y-4"
                    >
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

            {billing?.trial ? (
                <LemonBanner type="info" hideIcon className="mb-2">
                    <div className="flex items-center gap-4">
                        <JudgeHog className="w-20 h-20 flex-shrink-0" />
                        <div>
                            <p className="text-lg">You're on (a) trial</p>
                            <p>
                                You are currently on a free trial for <b>{toSentenceCase(billing.trial.target)} plan</b>{' '}
                                until <b>{dayjs(billing.trial.expires_at).format('LL')}</b>.
                                {billing.trial.type === 'autosubscribe' &&
                                    ' At the end of the trial you will be automatically subscribed to the plan.'}
                            </p>
                        </div>
                    </div>
                </LemonBanner>
            ) : null}

            {(showBillingSummary || showCreditCTAHero || showBillingHero) && !!size && (
                <div
                    className={clsx(
                        'flex gap-6 max-w-300',
                        // If there's no active subscription, BillingSummary is small so we stack it and invert order with CreditCTAHero or BillingHero
                        billing?.has_active_subscription
                            ? {
                                  'flex-col': size === 'small',
                                  'flex-row': size !== 'small',
                              }
                            : 'flex-col-reverse'
                    )}
                >
                    {showBillingSummary && (
                        <div className={clsx('flex-1', { 'flex-grow-0': showCreditCTAHero })}>
                            <BillingSummary />
                        </div>
                    )}
                    {(showCreditCTAHero || showBillingHero) && (
                        <div className={clsx('flex-1', { 'flex-grow-1': showCreditCTAHero })}>
                            {showCreditCTAHero && <CreditCTAHero />}
                            {showBillingHero && platformAndSupportProduct && (
                                <BillingHero product={platformAndSupportProduct} />
                            )}
                        </div>
                    )}
                </div>
            )}

            {!showBillingSummary && <StripePortalButton />}

            <LemonDivider className="mt-6 mb-8" />

            <div className="flex justify-between mt-4">
                <h2>Products</h2>
            </div>

            {products
                ?.filter(
                    (product: BillingProductV2Type) =>
                        !product.inclusion_only || product.plans.some((plan: BillingPlanType) => !plan.included_if)
                )
                ?.map((x: BillingProductV2Type) => (
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
