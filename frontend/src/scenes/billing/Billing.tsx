import './Billing.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { Field, Form } from 'kea-forms'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { LemonButton, LemonDivider, LemonInput, Link } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { JudgeHog } from 'lib/components/hedgehogs'
import { OrganizationMembershipLevel } from 'lib/constants'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { toSentenceCase } from 'lib/utils'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { BillingProductV2Type, ProductKey } from '~/types'

import { BillingHero } from './BillingHero'
import { BillingNoAccess } from './BillingNoAccess'
import { BillingProduct } from './BillingProduct'
import { BillingSummary } from './BillingSummary'
import { CreditCTAHero } from './CreditCTAHero'
import { StripePortalButton } from './StripePortalButton'
import { UnsubscribeCard } from './UnsubscribeCard'
import { billingLogic } from './billingLogic'

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
    const { featureFlags } = useValues(featureFlagLogic)
    const { location, searchParams } = useValues(router)

    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: OrganizationMembershipLevel.Admin,
        scope: RestrictionScope.Organization,
    })

    useEffect(() => {
        if (location.pathname === urls.organizationBilling() && featureFlags[FEATURE_FLAGS.USAGE_SPEND_DASHBOARDS]) {
            router.actions.replace(urls.organizationBillingSection('overview'), searchParams)
            return
        }
    }, [featureFlags, location.pathname, searchParams])

    useEffect(() => {
        if (billing) {
            reportBillingShown()
        }
    }, [!!billing]) // oxlint-disable-line react-hooks/exhaustive-deps

    if (preflight && !isCloudOrDev) {
        router.actions.push(urls.default())
    }

    if (!billing && billingLoading) {
        return (
            <>
                <SpinnerOverlay sceneLevel />
            </>
        )
    }

    if (restrictionReason) {
        return <BillingNoAccess reason={restrictionReason} />
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
        <div className="@container">
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
                <LemonBanner type="info" hideIcon className="max-w-300 mb-2">
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

            {(showBillingSummary || showCreditCTAHero || showBillingHero) && (
                <div
                    className={clsx(
                        'flex gap-6 max-w-300',
                        // If there's no active subscription, BillingSummary is small so we stack it and invert order with CreditCTAHero or BillingHero
                        billing?.has_active_subscription ? 'flex-col @3xl:flex-row' : 'flex-col-reverse'
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

            {featureFlags[FEATURE_FLAGS.BILLING_FORECASTING_ISSUES] && (
                <div className="flex mt-6 gap-6 max-w-300 flex-col-reverse">
                    <LemonBanner type="warning">
                        <strong>Note:</strong> Our forecasting engine is experiencing an issue. The projected amounts
                        may appear incorrect. We're working on a fix and it should be resolved soon.
                    </LemonBanner>
                </div>
            )}

            <div className="flex justify-between mt-4">
                <h2>Products</h2>
            </div>

            {products
                ?.filter(
                    (product: BillingProductV2Type) =>
                        !product.inclusion_only || product.addons.find((a) => !a.inclusion_only)
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
