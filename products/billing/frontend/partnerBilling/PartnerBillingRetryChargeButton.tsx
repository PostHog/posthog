import { useActions, useValues } from 'kea'

import { LemonButton, LemonDialog } from '@posthog/lemon-ui'

import type { PartnerPayerSettlementApi } from '../generated/api.schemas'
import { formatAmountCents } from './partnerBillingFormat'
import type { PartnerBillingLogicProps } from './partnerBillingLogic'
import { partnerBillingSettlementsLogic } from './partnerBillingSettlementsLogic'

interface PartnerBillingRetryChargeButtonProps extends PartnerBillingLogicProps {
    settlement: PartnerPayerSettlementApi
}

export function PartnerBillingRetryChargeButton({
    applicationId,
    settlement,
}: PartnerBillingRetryChargeButtonProps): JSX.Element {
    const logic = partnerBillingSettlementsLogic({ applicationId })
    const { retryingSettlementId } = useValues(logic)
    const { retrySettlement } = useActions(logic)
    const amount =
        settlement.amount_cents !== undefined ? formatAmountCents(settlement.amount_cents, settlement.currency) : null

    return (
        <LemonButton
            type="primary"
            size="small"
            loading={retryingSettlementId === settlement.settlement_id}
            disabledReason={
                retryingSettlementId && retryingSettlementId !== settlement.settlement_id
                    ? 'Another charge is in progress'
                    : undefined
            }
            onClick={() =>
                LemonDialog.open({
                    title: 'Retry this charge?',
                    description: amount
                        ? `PostHog charges ${amount} to the payment method on file.`
                        : 'PostHog charges the payment method on file.',
                    primaryButton: {
                        children: 'Retry charge',
                        onClick: () => retrySettlement(settlement),
                        'data-attr': 'partner-billing-confirm-retry-settlement',
                    },
                    secondaryButton: { children: 'Cancel' },
                })
            }
            data-attr="partner-billing-retry-settlement"
        >
            Retry charge
        </LemonButton>
    )
}
