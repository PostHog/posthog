import { useEffect } from 'react'
import { billingLogic } from './billingLogic'
import { LemonButton, LemonDivider, LemonInput, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { dayjs } from 'lib/dayjs'
import clsx from 'clsx'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { BillingHero } from './BillingHero'
import { PageHeader } from 'lib/components/PageHeader'
import { BillingProduct } from './BillingProduct'
import { IconPlus } from 'lib/lemon-ui/icons'
import { SceneExport } from 'scenes/sceneTypes'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { Field, Form } from 'kea-forms'

export const scene: SceneExport = {
    component: Billing,
    logic: billingLogic,
}

export function BillingPageHeader(): JSX.Element {
    return <PageHeader title="Billing &amp; usage" />
}

export function Billing(): JSX.Element {
    const {
        billing,
        billingLoading,
        redirectPath,
        isOnboarding,
        showLicenseDirectInput,
        isActivateLicenseSubmitting,
        isUnlicensedDebug,
    } = useValues(billingLogic)
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
                {!isOnboarding && <BillingPageHeader />}
                <LemonBanner type="error">
                    There was an issue retrieving your current billing information. If this message persists, please
                    {preflight?.cloud ? (
                        <Link onClick={() => openSupportForm('bug', 'billing')}>submit a bug report</Link>
                    ) : (
                        <Link to="mailto:sales@posthog.com">contact sales@posthog.com</Link>
                    )}
                    .
                </LemonBanner>
            </div>
        )
    }

    const products = billing?.products
    const getUpgradeAllProductsLink = (): string => {
        if (!products) {
            return ''
        }
        let url = '/api/billing-v2/activation?products='
        for (const product of products) {
            if (product.subscribed || product.contact_support || product.inclusion_only) {
                continue
            }
            const currentPlanIndex = product.plans.findIndex((plan) => plan.current_plan)
            const upgradePlanKey = isUnlicensedDebug
                ? product.plans?.[product.plans?.length - 1].plan_key
                : product.plans?.[currentPlanIndex + 1]?.plan_key
            if (!upgradePlanKey) {
                continue
            }
            url += `${product.type}:${upgradePlanKey},`
            if (product.addons?.length) {
                for (const addon of product.addons) {
                    url += `${addon.type}:${addon.plans[0].plan_key},`
                }
            }
        }
        // remove the trailing comma that will be at the end of the url
        url = url.slice(0, -1)
        if (redirectPath) {
            url += `&redirect_path=${redirectPath}`
        }
        return url
    }

    return (
        <div ref={ref}>
            {!isOnboarding && (
                <div className="flex justify-between">
                    <BillingPageHeader />
                    {billing?.has_active_subscription && (
                        <div>
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                to={billing.stripe_portal_url}
                                disableClientSideRouting
                                center
                            >
                                Manage card details
                            </LemonButton>
                        </div>
                    )}
                </div>
            )}
            {showLicenseDirectInput && (
                <>
                    <Form logic={billingLogic} formKey="activateLicense" enableFormOnSubmit className="space-y-4">
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
            )}
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
                </>
            )}
            <div
                className={clsx('flex flex-wrap gap-4', {
                    'flex-col pb-4 items-stretch': size === 'small',
                    'items-center': size !== 'small',
                })}
            >
                {!isOnboarding && billing?.billing_period && (
                    <div className="flex-1">
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
                    </div>
                )}

                <div
                    className={clsx('space-y-2', {
                        'p-4': size === 'medium',
                    })}
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ width: size === 'medium' ? '20rem' : undefined }}
                >
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

            <div className="flex justify-between">
                <h2>Products</h2>
                {isOnboarding && (
                    <LemonButton
                        type="primary"
                        icon={<IconPlus />}
                        to={getUpgradeAllProductsLink()}
                        disableClientSideRouting
                    >
                        Upgrade All
                    </LemonButton>
                )}
            </div>
            <LemonDivider className="mt-2 mb-8" />

            {products
                ?.filter((product) => !product.inclusion_only || product.contact_support)
                ?.map((x) => (
                    <div key={x.type}>
                        <BillingProduct product={x} />
                    </div>
                ))}
        </div>
    )
}
