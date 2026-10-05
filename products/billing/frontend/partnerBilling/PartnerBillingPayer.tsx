import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import type { PartnerPayerApplicationApi } from '../generated/api.schemas'
import { PartnerBillingInvoices } from './PartnerBillingInvoices'
import { partnerBillingLogic } from './partnerBillingLogic'
import { PartnerBillingOrganizations } from './PartnerBillingOrganizations'
import { PartnerBillingSettlements } from './PartnerBillingSettlements'
import { PartnerBillingSpending } from './PartnerBillingSpending'
import { PartnerBillingStatus } from './PartnerBillingStatus'
import { PartnerBillingWebhooks } from './PartnerBillingWebhooks'

export function PartnerBillingPayer({ application }: { application: PartnerPayerApplicationApi }): JSX.Element {
    const logic = partnerBillingLogic({ applicationId: application.id })
    const { payer, payerError, payerLoading } = useValues(logic)
    const { loadPartnerBillingPayer } = useActions(logic)

    if (!payer) {
        return payerError && !payerLoading ? (
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    onClick: () => loadPartnerBillingPayer(),
                    'data-attr': 'partner-billing-reload-payer',
                }}
            >
                {payerError}
            </LemonBanner>
        ) : (
            <LemonSkeleton className="h-32" />
        )
    }

    return (
        <div className="flex flex-col gap-10">
            <PartnerBillingStatus application={application} />
            {payer.billing_enabled !== false && (
                <>
                    <PartnerBillingWebhooks applicationId={application.id} />
                    <PartnerBillingSpending applicationId={application.id} />
                    <PartnerBillingOrganizations applicationId={application.id} />
                    <PartnerBillingInvoices applicationId={application.id} />
                    <PartnerBillingSettlements applicationId={application.id} />
                </>
            )}
        </div>
    )
}
