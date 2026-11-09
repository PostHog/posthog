import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { billingHelpLogic } from './billingHelpLogic'

export function BillingHelpCta(): JSX.Element {
    const { reportBillingHelpCtaClicked } = useActions(billingHelpLogic)

    return (
        <div
            className="mt-6 flex max-w-300 flex-wrap items-center justify-between gap-4 rounded-lg border bg-surface-primary p-4"
            data-attr="billing-help-cta"
        >
            <div className="min-w-0 flex-1">
                <h3 className="mb-1">Got questions about your bill?</h3>
                <p className="mb-0 text-secondary">
                    See who to contact, how pricing works, and ways to lower your spend.
                </p>
            </div>
            <LemonButton
                type="secondary"
                to={urls.organizationBillingSection('help')}
                onClick={() => reportBillingHelpCtaClicked()}
                data-attr="billing-help-cta-button"
            >
                Get help with your bill
            </LemonButton>
        </div>
    )
}
