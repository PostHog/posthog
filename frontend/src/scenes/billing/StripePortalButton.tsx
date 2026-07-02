import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { billingLogic } from './billingLogic'

export const StripePortalButton = (): JSX.Element | null => {
    const { billing } = useValues(billingLogic)

    if (!billing?.customer_id) {
        return null
    }

    const billingUrl = billing.external_billing_provider_invoices_url || billing.stripe_portal_url
    const label = billing.has_active_subscription ? 'Manage card details and invoices' : 'View past invoices'

    // A customer exists but no portal URL is available — show a disabled button with an explanation
    // rather than silently rendering nothing, which looks like a broken page.
    if (!billingUrl) {
        return (
            <div className="w-fit mt-4">
                <LemonButton
                    type="primary"
                    disabledReason="The billing portal is temporarily unavailable. Please refresh the page or contact support if this persists."
                    center
                    data-attr="manage-billing"
                >
                    {label}
                </LemonButton>
            </div>
        )
    }

    return (
        <div className="w-fit mt-4">
            <LemonButton
                type="primary"
                htmlType="submit"
                to={billingUrl}
                disableClientSideRouting
                targetBlank
                center
                data-attr="manage-billing"
            >
                {label}
            </LemonButton>
        </div>
    )
}
