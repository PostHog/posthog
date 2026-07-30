import { useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { BillingUpgradeCTA } from 'lib/components/BillingUpgradeCTA'
import { pluralize } from 'lib/utils/strings'
import { billingLogic } from 'scenes/billing/billingLogic'
import { findInboxProduct, freePrs, pricePerPrUsd } from 'scenes/billing/inboxPricing'
import { paymentEntryLogic } from 'scenes/billing/paymentEntryLogic'
import { onboardingEventUsageLogic } from 'scenes/onboarding/onboardingEventUsageLogic'
import { availableOnboardingProducts } from 'scenes/onboarding/shared/utils'

import { ProductKey } from '~/queries/schema/schema-general'
import { type BillingProductV2Type } from '~/types'

/**
 * Billing step for the self-driving onboarding, and the last screen before the inbox.
 *
 * The thing being sold here is shipped work: agents watch and report for free, and a PR that lands
 * is what costs money. Every number comes off the billing product (`inbox`) rather than being
 * written down here, so a pricing change lands without a frontend deploy.
 *
 * No flow navigation lives here; the parent shell owns Back/Continue. The only action this step
 * fires is the payment-entry flow, which opens the globally mounted PaymentEntryModal (see
 * layout/GlobalModals) over the card and returns to the same URL.
 */

const formatUsd = (usd: number): string => (Number.isInteger(usd) ? `$${usd}` : `$${usd.toFixed(2)}`)

const compact = (value: number): string =>
    Intl.NumberFormat('en', { notation: 'compact', compactDisplay: 'short', maximumFractionDigits: 1 }).format(value)

/**
 * The headline: what self-driving costs, before the plans that differ only in what happens after
 * the free PRs run out.
 *
 * The numbers are optional on purpose. Billing may not carry the inbox product (an instance without
 * it in its plans config, or a request that came back thin), and the pricing model is still the
 * point of this screen, so the copy stands on its own and only the figures drop out.
 */
function SelfDrivingPricing({ product }: { product: BillingProductV2Type | null }): JSX.Element {
    const included = freePrs(product)
    const perPr = pricePerPrUsd(product)

    return (
        <div className="w-full flex flex-col gap-3 p-4 rounded-lg border border-accent bg-accent-highlight">
            <p className="m-0 text-sm font-semibold">You pay for shipped work, nothing else</p>
            {(included > 0 || perPr !== null) && (
                <div className="flex flex-wrap items-start gap-x-10 gap-y-3">
                    {included > 0 && (
                        <div>
                            <p className="m-0 text-2xl font-bold leading-tight">{included}</p>
                            <p className="m-0 text-xs text-muted">
                                {pluralize(included, 'pull request', undefined, false)} a month, free
                            </p>
                        </div>
                    )}
                    {perPr !== null && (
                        <div>
                            <p className="m-0 text-2xl font-bold leading-tight">{formatUsd(perPr)}</p>
                            <p className="m-0 text-xs text-muted">per pull request after that</p>
                        </div>
                    )}
                </div>
            )}
            <p className="m-0 text-xs text-muted">
                Scouts, signals, and reports never cost anything. You're charged only when an agent ships a pull request
                you can review.
            </p>
        </div>
    )
}

/**
 * Monthly free allowance on the tools the wizard turns on, so the plan reads as the whole platform
 * rather than PRs alone. It sits under both plans because subscribing changes nothing about it:
 * every tool keeps the same free tier either way.
 */
function ToolFreeTiers({ products }: { products: BillingProductV2Type[] | undefined }): JSX.Element | null {
    const allowances = (products ?? [])
        .filter((product) => product.type in availableOnboardingProducts)
        .map((product) => {
            const freePlan = product.plans.find((plan) => plan.plan_key?.startsWith('free'))
            return { name: product.name, unit: freePlan?.unit ?? '', value: freePlan?.free_allocation ?? 0 }
        })
        .filter((allowance) => allowance.unit && allowance.value > 0)

    if (allowances.length === 0) {
        return null
    }

    return (
        <div className="w-full flex flex-col gap-2">
            <p className="m-0 text-xs text-muted">Every other tool keeps its free tier on both plans:</p>
            <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 m-0 p-0 list-none">
                {allowances.map(({ name, unit, value }) => (
                    <li key={name} className="flex items-center gap-2">
                        <IconCheck className="size-3.5 text-success shrink-0" />
                        <span className="text-xs text-muted">
                            <strong className="font-semibold text-default">{name}</strong>: {compact(value)}{' '}
                            {pluralize(value, unit, undefined, false)} a month
                        </span>
                    </li>
                ))}
            </ul>
        </div>
    )
}

function SubscribedState({ onContinue }: { onContinue: () => void }): JSX.Element {
    return (
        <div className="flex flex-col gap-3">
            <div className="flex items-start gap-3 p-4 border border-success rounded-lg bg-success-highlight">
                <IconCheck className="size-5 text-success shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0">
                    <p className="m-0 text-sm font-semibold">You're on pay-as-you-go</p>
                    <p className="m-0 text-xs text-muted">
                        Agents keep watching and reporting for free. You only pay when one ships a PR.
                    </p>
                </div>
            </div>
            <p className="text-xs text-muted m-0">Change or cancel any time from billing settings.</p>
            <LemonButton type="primary" status="alt" onClick={onContinue} className="self-end">
                Go to your inbox
            </LemonButton>
        </div>
    )
}

function PlanChoice({
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

export function BillingStep({ onContinue }: { onContinue: () => void }): JSX.Element {
    const { billing, billingLoading } = useValues(billingLogic)

    if (!billing && billingLoading) {
        return (
            <div className="flex items-center justify-center py-12">
                <Spinner className="text-2xl text-muted size-8" />
            </div>
        )
    }

    // Either billing isn't set up on this instance (self-hosted without a license, or local dev) or
    // the request failed. We can't tell them apart from here, and neither is worth blocking setup
    // over, so say what we know and keep the flow moving.
    if (!billing) {
        return (
            <div className="flex flex-col gap-3">
                <p className="text-sm text-muted m-0">
                    We couldn't load billing just now. Nothing is blocked. Your agents are set up, and you can pick a
                    plan later from billing settings.
                </p>
                <div className="flex items-center justify-between gap-2">
                    <LemonButton type="secondary" to="https://posthog.com/pricing" targetBlank>
                        See pricing
                    </LemonButton>
                    <LemonButton type="primary" status="alt" onClick={onContinue}>
                        Go to your inbox
                    </LemonButton>
                </div>
            </div>
        )
    }

    if (billing.has_active_subscription) {
        return <SubscribedState onContinue={onContinue} />
    }

    // Subscribing still activates the whole catalog (billing expands `all_products:` server-side),
    // so the platform product stays the thing we hand the payment flow. The inbox product is what
    // this screen actually talks about, and where its numbers come from.
    const platformProduct =
        billing.products?.find((product) => product.type === ProductKey.PLATFORM_AND_SUPPORT) ?? null

    return (
        <PlanChoice
            platformProduct={platformProduct}
            inboxProduct={findInboxProduct(billing.products)}
            products={billing.products}
            onContinue={onContinue}
        />
    )
}
