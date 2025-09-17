import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { billingLogic } from './billingLogic'

export const StripePortalButton = (): JSX.Element | null => {
    const { billing } = useValues(billingLogic)

    if (!billing?.customer_id || !billing?.stripe_portal_url) {
        return null
    }

    return (
        <div className="w-fit mt-4">
            <LemonButton
                type="primary"
                htmlType="submit"
                to={billing.stripe_portal_url}
                disableClientSideRouting
                targetBlank
                center
                data-attr="manage-billing"
            >
                {billing.has_active_subscription ? 'Manage card details and invoices' : 'View past invoices'}
            </LemonButton>
        </div>
    )
}
