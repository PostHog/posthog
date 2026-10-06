import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, LemonSkeleton } from '@posthog/lemon-ui'

import { PartnerBillingDetail } from './PartnerBillingDetail'
import { formatAmountCents, formatBillingPeriod, formatSettlementCharge } from './partnerBillingFormat'
import { PartnerBillingInvoiceTable } from './PartnerBillingInvoiceTable'
import type { PartnerBillingLogicProps } from './partnerBillingLogic'
import { PartnerBillingRetryChargeButton } from './PartnerBillingRetryChargeButton'
import { isRetryableSettlement, partnerBillingSettlementsLogic } from './partnerBillingSettlementsLogic'
import { PartnerBillingStatusTag } from './PartnerBillingStatusTag'

export function PartnerBillingSettlementModal({ applicationId }: PartnerBillingLogicProps): JSX.Element {
    const logic = partnerBillingSettlementsLogic({ applicationId })
    const { openedSettlementId, openedSettlement, openedSettlementLoading, openedSettlementError } = useValues(logic)
    const { closeSettlement, openSettlement } = useActions(logic)
    const charge = openedSettlement ? formatSettlementCharge(openedSettlement) : null
    const creditAmount = openedSettlement?.credit_amount_cents ?? 0

    return (
        <LemonModal
            isOpen={!!openedSettlementId}
            onClose={closeSettlement}
            title="Settlement"
            width={800}
            footer={
                <LemonButton type="secondary" onClick={closeSettlement}>
                    Close
                </LemonButton>
            }
        >
            {openedSettlementError && !openedSettlementLoading ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => openedSettlementId && openSettlement(openedSettlementId),
                        'data-attr': 'partner-billing-reload-settlement',
                    }}
                >
                    {openedSettlementError}
                </LemonBanner>
            ) : !openedSettlement ? (
                <LemonSkeleton className="h-32" />
            ) : (
                <div className="flex flex-col gap-6">
                    <div className="flex flex-wrap items-end gap-x-10 gap-y-4">
                        <PartnerBillingDetail label="Period">
                            {formatBillingPeriod(openedSettlement.period_start, openedSettlement.period_end)}
                        </PartnerBillingDetail>
                        {creditAmount > 0 && openedSettlement.gross_amount_cents !== undefined && (
                            <PartnerBillingDetail label="Invoice total">
                                {formatAmountCents(openedSettlement.gross_amount_cents, openedSettlement.currency)}
                            </PartnerBillingDetail>
                        )}
                        {creditAmount > 0 && (
                            <PartnerBillingDetail label="Credits applied">
                                {formatAmountCents(creditAmount, openedSettlement.currency)}
                            </PartnerBillingDetail>
                        )}
                        {openedSettlement.amount_cents !== undefined && (
                            <PartnerBillingDetail label={creditAmount > 0 ? 'Net charge' : 'Amount'}>
                                {formatAmountCents(openedSettlement.amount_cents, openedSettlement.currency)}
                            </PartnerBillingDetail>
                        )}
                        {openedSettlement.status && (
                            <PartnerBillingDetail label="Status">
                                <PartnerBillingStatusTag status={openedSettlement.status} />
                            </PartnerBillingDetail>
                        )}
                        {charge && <PartnerBillingDetail label="Charge">{charge}</PartnerBillingDetail>}
                        {isRetryableSettlement(openedSettlement) && (
                            <PartnerBillingRetryChargeButton
                                applicationId={applicationId}
                                settlement={openedSettlement}
                            />
                        )}
                    </div>
                    <div className="flex flex-col gap-2">
                        <h4 className="text-sm font-semibold mb-0">Invoices this settlement pays</h4>
                        <PartnerBillingInvoiceTable
                            applicationId={applicationId}
                            invoices={openedSettlement.invoices ?? []}
                            loading={openedSettlementLoading}
                            emptyState="This settlement doesn't pay any invoices."
                            showCharged
                            chargedColumnTitle={creditAmount > 0 ? 'Amount settled' : undefined}
                        />
                    </div>
                </div>
            )}
        </LemonModal>
    )
}
