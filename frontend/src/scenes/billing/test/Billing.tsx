import { useEffect } from 'react'
import { billingLogic } from '../billingLogic'
import { LemonButton, LemonDivider, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { SpinnerOverlay } from 'lib/lemon-ui/Spinner/Spinner'
import { AlertMessage } from 'lib/lemon-ui/AlertMessage'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { dayjs } from 'lib/dayjs'
import clsx from 'clsx'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { capitalizeFirstLetter } from 'lib/utils'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { BillingHero } from '../BillingHero'
import { PageHeader } from 'lib/components/PageHeader'
import BillingProduct from '../BillingProduct'
import { BillingProduct as BillingProductTest } from './BillingProduct'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { FEATURE_FLAGS } from 'lib/constants'

export function BillingPageHeader(): JSX.Element {
    return <PageHeader title="Billing &amp; usage" />
}

export function Billing(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { billing, billingLoading } = useValues(billingLogic)
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
                </>
            )}
            <div
                className={clsx('flex flex-wrap gap-4', {
                    'flex-col pb-4 items-stretch': size === 'small',
                    'items-center': size !== 'small',
                })}
            >
                {billing?.billing_period && (
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

            <h2>Products</h2>
            <LemonDivider className="mt-2 mb-8" />

            {products?.map((x) => (
                <div key={x.type}>
                    {featureFlags[FEATURE_FLAGS.BILLING_BY_PRODUCTS] === 'test' ? (
                        <BillingProductTest product={x} />
                    ) : (
                        <>
                            <LemonDivider dashed className="my-2" />
                            <BillingProduct product={x} />
                        </>
                    )}
                </div>
            ))}
        </div>
    )
}
