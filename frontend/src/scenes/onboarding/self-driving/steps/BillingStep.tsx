import { useValues } from 'kea'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { billingLogic } from 'scenes/billing/billingLogic'
import { findInboxProduct } from 'scenes/billing/inboxPricing'
import { PlanChoice } from 'scenes/onboarding/self-driving/components/PlanChoice'
import { SubscribedState } from 'scenes/onboarding/self-driving/components/SubscribedState'

import { ProductKey } from '~/queries/schema/schema-general'

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
export function BillingStep({ onContinue, completing }: { onContinue: () => void; completing: boolean }): JSX.Element {
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
                    <LemonButton type="primary" status="alt" onClick={onContinue} loading={completing}>
                        Go to your inbox
                    </LemonButton>
                </div>
            </div>
        )
    }

    if (billing.has_active_subscription) {
        return <SubscribedState onContinue={onContinue} completing={completing} />
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
            completing={completing}
        />
    )
}
