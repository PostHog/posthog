import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTag } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'

import type { PartnerPayerApplicationApi } from '../generated/api.schemas'
import { PartnerBillingDetail } from './PartnerBillingDetail'
import { formatAddress, formatTaxId } from './partnerBillingFormat'
import { partnerBillingLogic } from './partnerBillingLogic'

export function PartnerBillingStatus({ application }: { application: PartnerPayerApplicationApi }): JSX.Element | null {
    const logic = partnerBillingLogic({ applicationId: application.id })
    const { payer, billingPortalLoading } = useValues(logic)
    const { openPartnerBillingPortal } = useActions(logic)
    const { openSupportForm } = useActions(supportLogic)

    if (!payer) {
        return null
    }

    if (payer.billing_enabled === false) {
        return (
            <LemonBanner
                type="info"
                action={{
                    children: 'Contact us',
                    onClick: () => openSupportForm({ kind: 'support', billing_issue: true, isEmailFormOpen: true }),
                    'data-attr': 'partner-billing-contact-support',
                }}
            >
                Partner billing is off for <strong>{application.name}</strong>. PostHog turns it on for you, so contact
                us to get started.
            </LemonBanner>
        )
    }

    const billingDetails = payer.billing_details
    const address = formatAddress(billingDetails?.address)
    const taxIds = billingDetails?.tax_ids ?? []

    return (
        <section className="flex flex-col gap-4">
            {payer.past_due && (
                <LemonBanner type="error">
                    A monthly charge failed, so your payments are past due. Update your payment details if they changed,
                    then retry the charge under Settlements.
                </LemonBanner>
            )}
            {payer.spend?.capped && (
                <LemonBanner type="warning">
                    Spend this month reached your cap, so billing caps further usage across the organizations you pay
                    for. Raise or remove the cap under Spending to lift it.
                </LemonBanner>
            )}
            <div className="flex flex-wrap gap-x-10 gap-y-4">
                {payer.billing_enabled && (
                    <PartnerBillingDetail label="Status">
                        <LemonTag type="success">On</LemonTag>
                    </PartnerBillingDetail>
                )}
                {payer.name && <PartnerBillingDetail label="Billed to">{payer.name}</PartnerBillingDetail>}
                {payer.has_payment_method !== undefined && (
                    <PartnerBillingDetail label="Payment method">
                        {payer.has_payment_method ? 'Added' : 'Not added yet'}
                    </PartnerBillingDetail>
                )}
                {payer.organization_count !== undefined && (
                    <PartnerBillingDetail label="Organizations">{payer.organization_count}</PartnerBillingDetail>
                )}
            </div>
            {billingDetails && (
                <div className="flex flex-wrap gap-x-10 gap-y-4">
                    <PartnerBillingDetail label="Billing address">
                        <span className="inline-block max-w-80">{address ?? 'Not added yet'}</span>
                    </PartnerBillingDetail>
                    <PartnerBillingDetail label="Tax IDs">
                        {taxIds.length > 0 ? taxIds.map(formatTaxId).join(', ') : 'None added'}
                    </PartnerBillingDetail>
                </div>
            )}
            <div className="flex flex-col items-start gap-1">
                <LemonButton
                    type={payer.has_payment_method ? 'secondary' : 'primary'}
                    onClick={() => openPartnerBillingPortal()}
                    loading={billingPortalLoading}
                    data-attr="partner-billing-open-portal"
                >
                    {payer.has_payment_method ? 'Update payment details' : 'Set up payment'}
                </LemonButton>
                <p className="text-secondary text-xs mb-0">
                    You add your card, billing address, and tax IDs in the billing portal, then come back here.
                </p>
            </div>
        </section>
    )
}
