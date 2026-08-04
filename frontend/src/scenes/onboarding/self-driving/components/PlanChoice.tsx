import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { pluralize } from 'lib/utils/strings'
import { freePrs, pricePerPrUsd } from 'scenes/billing/inboxPricing'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'
import { onboardingEventUsageLogic } from 'scenes/onboarding/onboardingEventUsageLogic'
import { PlanCard } from 'scenes/onboarding/self-driving/components/PlanCard'
import { SelfDrivingPricing } from 'scenes/onboarding/self-driving/components/SelfDrivingPricing'
import { ToolFreeTiers } from 'scenes/onboarding/self-driving/components/ToolFreeTiers'
import { formatUsd } from 'scenes/onboarding/self-driving/utils'
import { CheckList } from 'scenes/onboarding/shared/components/CheckList'

import { type BillingProductV2Type } from '~/types'

/** The free vs pay-as-you-go pick, under the pricing headline. */
export function PlanChoice({
    platformProduct,
    inboxProduct,
    products,
    onContinue,
    completing,
}: {
    platformProduct: BillingProductV2Type | null
    inboxProduct: BillingProductV2Type | null
    products: BillingProductV2Type[] | undefined
    onContinue: () => void
    /** The free pick finishes onboarding, which writes to the team before navigating. */
    completing: boolean
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

            <PlanCard
                title="Free"
                priceLabel="$0 / month"
                footnote="Agents pause shipping once the free pull requests are used up, instead of charging you."
                cta={
                    <LemonButton
                        type="secondary"
                        fullWidth
                        center
                        onClick={continueFree}
                        loading={completing}
                        data-attr="self-driving-onboarding-free"
                    >
                        Start free
                    </LemonButton>
                }
            >
                <CheckList
                    items={[
                        {
                            content:
                                included > 0 ? (
                                    <>
                                        <strong>{pluralize(included, 'pull request', undefined)}</strong> a month,
                                        shipped and reviewed
                                    </>
                                ) : (
                                    'A monthly allowance of shipped pull requests'
                                ),
                        },
                        { content: 'No payment method needed' },
                    ]}
                />
            </PlanCard>

            <PlanCard
                title="Pay-as-you-go"
                titleCaption="Free allowance included"
                priceLabel={perPrUsd !== null ? `${formatUsd(perPrUsd)} per shipped PR` : null}
                highlighted
                cta={
                    <BillingUpgradeCTA
                        type="primary"
                        status="alt"
                        fullWidth
                        center
                        loading={subscribing}
                        disabledReason={subscribing ? 'Opening payment…' : undefined}
                        disableClientSideRouting
                        onClick={subscribe}
                        data-attr="self-driving-onboarding-subscribe"
                    >
                        Add payment method
                    </BillingUpgradeCTA>
                }
            >
                <CheckList
                    items={[
                        { content: 'Agents keep shipping past the free allowance' },
                        { content: 'Set a spend limit whenever you want' },
                    ]}
                />
            </PlanCard>

            <ToolFreeTiers products={products} />
        </div>
    )
}
