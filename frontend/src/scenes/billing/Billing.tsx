import { useEffect } from 'react'
import { billingLogic } from './billingLogic'
import { LemonButton, LemonDivider, LemonInput, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { dayjs } from 'lib/dayjs'
import clsx from 'clsx'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { PlanTable } from './PlanTable'
import { BillingHero } from './BillingHero'
import { PageHeader } from 'lib/components/PageHeader'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import BillingProduct from './BillingProduct'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { Billing as BillingTest } from './test/Billing'
import { Field, Form } from 'kea-forms'
import { supportLogic } from 'lib/components/Support/supportLogic'

export const scene: SceneExport = {
    component: Billing,
    logic: billingLogic,
}

export function BillingPageHeader(): JSX.Element {
    return <PageHeader title="Billing &amp; usage" />
}

export function Billing(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { billing, billingLoading, isActivateLicenseSubmitting, showLicenseDirectInput } = useValues(billingLogic)
    const { reportBillingV2Shown } = useActions(billingLogic)
    const { preflight } = useValues(preflightLogic)
    const cloudOrDev = preflight?.cloud || preflight?.is_debug
    const { openSupportForm } = useActions(supportLogic)

    useEffect(() => {
        if (billing) {
            reportBillingV2Shown()
        }
    }, [!!billing])

    const { ref, size } = useResizeBreakpoints({
        0: 'small',
        1000: 'medium',
    })

    if (featureFlags[FEATURE_FLAGS.BILLING_BY_PRODUCTS] === 'test') {
        return <BillingTest />
    }

    if (!billing && billingLoading) {
        return (
            <>
                <BillingPageHeader />
                <SpinnerOverlay />
            </>
        )
    }

    if (!billing && !billingLoading) {
        return (
            <div className="space-y-4">
                <BillingPageHeader />
                <LemonBanner type="error">
                    There was an issue retrieving your current billing information. If this message persists please{' '}
                    <Link
                        onClick={() => {
                            openSupportForm('bug', 'billing')
                        }}
                    >
                        submit a bug report
                    </Link>
                    .
                </LemonBanner>

                {!cloudOrDev ? (
                    <LemonBanner type="info">
                        There was an issue retrieving your current billing information. If this message persists please
                        contact <Link to="mailto:sales@posthog.com">sales@posthog.com</Link>.
                    </LemonBanner>
                ) : null}
            </div>
        )
    }

    const products = billing?.products

    return (
        <div ref={ref}>
            <BillingPageHeader />
            {billing?.free_trial_until ? (
                <LemonBanner type="success" className="mb-2">
                    You are currently on a free trial until <b>{billing.free_trial_until.format('LL')}</b>
                </LemonBanner>
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

            {(products || [])
                .filter((x) => !x.inclusion_only)
                .map((x) => (
                    <div key={x.type}>
                        <LemonDivider dashed className="my-2" />
                        <BillingProduct product={x} />
                    </div>
                ))}
        </div>
    )
}
