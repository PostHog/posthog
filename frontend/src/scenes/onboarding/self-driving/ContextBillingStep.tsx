import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { pluralize } from 'lib/utils/strings'
import { billingLogic } from 'scenes/billing/billingLogic'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'
import { availableOnboardingProducts } from 'scenes/onboarding/shared/utils'

import { ProductKey } from '~/queries/schema/schema-general'
import { type BillingProductV2Type } from '~/types'

/**
 * Inline billing step body for the context-first onboarding flow.
 *
 * No flow navigation lives here; the parent shell owns Back/Continue/Skip. The only action this
 * step fires is the payment-entry flow, which opens the globally mounted PaymentEntryModal (see
 * layout/GlobalModals) over the card and returns to the same URL. Nothing here redirects away.
 */

// Compact free-tier allowance, shown so "start free" reads as an honest offer rather than a teaser.
function FreeTierRow({ value, unit, name }: { value: number; unit: string; name: string }): JSX.Element {
    const formatted = Intl.NumberFormat('en', {
        notation: 'compact',
        compactDisplay: 'short',
        maximumFractionDigits: 1,
    }).format(value)

    return (
        <li className="flex items-center gap-2">
            <IconCheck className="size-4 text-success shrink-0" />
            <span className="text-sm">
                <strong>
                    {formatted} {pluralize(value, unit, undefined, false)}
                </strong>{' '}
                <span className="text-muted">/ month {name}, free</span>
            </span>
        </li>
    )
}

function FreeTierSummary(): JSX.Element | null {
    const { billing } = useValues(billingLogic)

    const allowances = (billing?.products ?? [])
        .filter((product) => product.type in availableOnboardingProducts)
        .map((product) => {
            const freePlan = product.plans.find((plan) => plan.plan_key?.startsWith('free'))
            return {
                name: product.name,
                unit: freePlan?.unit ?? '',
                value: freePlan?.free_allocation ?? 0,
            }
        })
        .filter((allowance) => allowance.unit && allowance.value > 0)

    if (allowances.length === 0) {
        return null
    }

    return (
        <ul className="flex flex-col gap-1.5 m-0 p-0 list-none">
            {allowances.map((allowance) => (
                <FreeTierRow key={allowance.name} value={allowance.value} unit={allowance.unit} name={allowance.name} />
            ))}
        </ul>
    )
}

function SubscribedState({ onContinue }: { onContinue: () => void }): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-start gap-3 p-4 border border-success rounded-lg bg-success-highlight">
                <IconCheck className="size-5 text-success shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                    <p className="m-0 text-sm font-semibold">You're on the pay-as-you-go plan</p>
                    <p className="m-0 text-xs text-muted">
                        Every tool is unlocked. You still get the monthly free tier on each. You only pay for usage
                        beyond it.
                    </p>
                </div>
            </div>
            <p className="text-xs text-muted m-0">Change or cancel any time from billing settings.</p>
            <LemonButton type="primary" status="alt" onClick={onContinue} className="self-end">
                Continue
            </LemonButton>
        </div>
    )
}

function PlanChoice({
    platformProduct,
    onContinue,
}: {
    platformProduct: BillingProductV2Type | null
    onContinue: () => void
}): JSX.Element {
    const { startPaymentEntryFlow } = useActions(paymentEntryLogic)
    const { reportContextOnboardingPlanSelected } = useActions(eventUsageLogic)
    // Guard the subscribe button against double-submit: `isLoading` covers the returning-customer
    // activate call, `paymentEntryModalOpen` covers a new customer once the Stripe modal is up.
    const { isLoading, paymentEntryModalOpen } = useValues(paymentEntryLogic)
    const subscribing = isLoading || paymentEntryModalOpen

    // Reported at the pick, not at payment completion — whether payment then resolves is billing's
    // own funnel (GROW-89).
    const subscribe = (): void => {
        reportContextOnboardingPlanSelected('pay_as_you_go')
        // Returning the user to the same URL keeps them in the onboarding flow once payment resolves.
        startPaymentEntryFlow(platformProduct, window.location.pathname + window.location.search)
    }
    const continueFree = (): void => {
        reportContextOnboardingPlanSelected('free')
        onContinue()
    }

    return (
        <div className="flex flex-wrap gap-3">
            <p className="text-sm text-muted m-0 w-full">
                Start free, no card required. You only pay for usage past the monthly free tier on each tool.
            </p>

            <div className="flex flex-1 basis-72 flex-col gap-3 p-4 border border-primary rounded-lg">
                <div className="flex items-baseline justify-between gap-2">
                    <p className="m-0 text-base font-semibold">Free</p>
                    <p className="m-0 text-sm text-muted">$0 / month</p>
                </div>
                <FreeTierSummary />
                <p className="m-0 text-xs text-muted">
                    Usage pauses at the free tier instead of charging you. Good for trying things out.
                </p>
                <LemonButton
                    type="secondary"
                    fullWidth
                    center
                    onClick={continueFree}
                    className="mt-auto"
                    data-attr="context-onboarding-free"
                >
                    Continue on free
                </LemonButton>
            </div>

            <div className="flex flex-1 basis-72 flex-col gap-3 p-4 border-2 border-accent rounded-lg">
                <div className="flex items-baseline justify-between gap-2">
                    <div>
                        <p className="m-0 text-base font-semibold">Pay-as-you-go</p>
                        <p className="m-0 text-xs text-muted">Free tier included</p>
                    </div>
                    <p className="m-0 text-sm text-muted">based on usage</p>
                </div>
                <ul className="flex flex-col gap-1.5 m-0 p-0 list-none">
                    {[
                        'Every tool unlocked, no caps',
                        'Same monthly free tier on each tool',
                        'Add a card now, pay only past the free tier',
                    ].map((line) => (
                        <li key={line} className="flex items-center gap-2">
                            <IconCheck className="size-4 text-success shrink-0" />
                            <span className="text-sm">{line}</span>
                        </li>
                    ))}
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
                    data-attr="context-onboarding-subscribe"
                >
                    Add payment method
                </BillingUpgradeCTA>
            </div>
        </div>
    )
}

export function ContextBillingStep({ onContinue }: { onContinue: () => void }): JSX.Element {
    const { billing, billingLoading } = useValues(billingLogic)

    if (!billing && billingLoading) {
        return (
            <div className="flex items-center justify-center py-12">
                <Spinner className="text-2xl text-muted size-8" />
            </div>
        )
    }

    // No billing at all (e.g. self-hosted without a license), so nothing to subscribe to here.
    if (!billing) {
        return (
            <div className="flex flex-col gap-3">
                <p className="text-sm text-muted m-0">
                    Billing isn't configured on this instance, so there's nothing to pick here.
                </p>
                <div className="flex items-center justify-between gap-2">
                    <LemonButton type="secondary" to="https://posthog.com/pricing" targetBlank>
                        See pricing
                    </LemonButton>
                    <LemonButton type="primary" status="alt" onClick={onContinue}>
                        Continue
                    </LemonButton>
                </div>
            </div>
        )
    }

    if (billing.has_active_subscription) {
        return <SubscribedState onContinue={onContinue} />
    }

    const platformProduct =
        billing.products?.find((product) => product.type === ProductKey.PLATFORM_AND_SUPPORT) ?? null

    return <PlanChoice platformProduct={platformProduct} onContinue={onContinue} />
}
