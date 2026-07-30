import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { pluralize } from 'lib/utils/strings'
import { freePrs, pricePerPrUsd } from 'scenes/billing/inboxPricing'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'
import { onboardingEventUsageLogic } from 'scenes/onboarding/onboardingEventUsageLogic'
import { SelfDrivingPricing } from 'scenes/onboarding/self-driving/components/SelfDrivingPricing'
import { ToolFreeTiers } from 'scenes/onboarding/self-driving/components/ToolFreeTiers'
import { formatUsd } from 'scenes/onboarding/self-driving/utils'

import { type BillingProductV2Type } from '~/types'

/** The free vs pay-as-you-go pick, under the pricing headline. */
export function PlanChoice({
    platformProduct,
    inboxProduct,
    products,
    onContinue,
}: {
    platformProduct: BillingProductV2Type | null
    inboxProduct: BillingProductV2Type | null
    products: BillingProductV2Type[] | undefined
    onContinue: () => void
}): JSX.Element {
    const { startPaymentEntryFlow } = useActions(paymentEntryLogic)
    const { reportSelfDrivingOnboardingPlanSelected } = useActions(onboardingEventUsageLogic)
    // Guard the subscribe button against double-submit: `isLoading` covers the returning-customer
    // activate call, `paymentEntryModalOpen` covers a new customer once the Stripe modal is up.
    const { isLoading, paymentEntryModalOpen } = useValues(paymentEntryLogic)
    const subscribing = isLoading || paymentEntryModalOpen

    const included = freePrs(inboxProduct)
    const perPrUsd = pricePerPrUsd(inboxProduct)

    // Reported at the pick, not at payment completion — whether payment then resolves is billing's
    // own funnel (GROW-89).
    const subscribe = (): void => {
        reportSelfDrivingOnboardingPlanSelected('pay_as_you_go')
        // Returning the user to the same URL keeps them in the onboarding flow once payment resolves.
        startPaymentEntryFlow(platformProduct, window.location.pathname + window.location.search)
    }
    const continueFree = (): void => {
        reportSelfDrivingOnboardingPlanSelected('free')
        onContinue()
    }

    return (
        <div className="flex flex-wrap gap-3">
            <SelfDrivingPricing product={inboxProduct} />

            <div className="flex flex-1 basis-72 flex-col gap-3 p-4 border border-primary rounded-lg">
                <div className="flex items-baseline justify-between gap-2">
                    <p className="m-0 text-base font-semibold">Free</p>
                    <p className="m-0 text-sm text-muted">$0 / month</p>
                </div>
                <ul className="flex flex-col gap-1.5 m-0 p-0 list-none">
                    <li className="flex items-center gap-2">
                        <IconCheck className="size-4 text-success shrink-0" />
                        <span className="text-sm">
                            {included > 0 ? (
                                <>
                                    <strong>{pluralize(included, 'pull request', undefined)}</strong> a month, shipped
                                    and reviewed
                                </>
                            ) : (
                                'A monthly allowance of shipped pull requests'
                            )}
                        </span>
                    </li>
                    <li className="flex items-center gap-2">
                        <IconCheck className="size-4 text-success shrink-0" />
                        <span className="text-sm">No payment method needed</span>
                    </li>
                </ul>
                <p className="m-0 text-xs text-muted">
                    Agents pause shipping once the free pull requests are used up, instead of charging you.
                </p>
                <LemonButton
                    type="secondary"
                    fullWidth
                    center
                    onClick={continueFree}
                    className="mt-auto"
                    data-attr="self-driving-onboarding-free"
                >
                    Start free
                </LemonButton>
            </div>

            <div className="flex flex-1 basis-72 flex-col gap-3 p-4 border-2 border-accent rounded-lg">
                <div className="flex items-baseline justify-between gap-2">
                    <div>
                        <p className="m-0 text-base font-semibold">Pay-as-you-go</p>
                        <p className="m-0 text-xs text-muted">Free allowance included</p>
                    </div>
                    {perPrUsd !== null && (
                        <p className="m-0 text-sm text-muted">{formatUsd(perPrUsd)} per shipped PR</p>
                    )}
                </div>
                <ul className="flex flex-col gap-1.5 m-0 p-0 list-none">
                    <li className="flex items-center gap-2">
                        <IconCheck className="size-4 text-success shrink-0" />
                        <span className="text-sm">Agents keep shipping past the free allowance</span>
                    </li>
                    <li className="flex items-center gap-2">
                        <IconCheck className="size-4 text-success shrink-0" />
                        <span className="text-sm">Set a spend limit whenever you want</span>
                    </li>
                </ul>
                <BillingUpgradeCTA
                    type="primary"
                    status="alt"
                    fullWidth
                    center
                    className="mt-auto"
                    loading={subscribing}
                    disabledReason={subscribing ? 'Opening payment…' : undefined}
                    disableClientSideRouting
                    onClick={subscribe}
                    data-attr="self-driving-onboarding-subscribe"
                >
                    Add payment method
                </BillingUpgradeCTA>
            </div>

            <ToolFreeTiers products={products} />
        </div>
    )
}
