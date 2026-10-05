import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTable } from '@posthog/lemon-ui'

import { formatAmountCents, formatBillingPeriod, formatSettlementCharge } from './partnerBillingFormat'
import type { PartnerBillingLogicProps } from './partnerBillingLogic'
import { partnerBillingTablePagination } from './partnerBillingPagination'
import { PartnerBillingRetryChargeButton } from './PartnerBillingRetryChargeButton'
import { PartnerBillingSettlementModal } from './PartnerBillingSettlementModal'
import { isRetryableSettlement, partnerBillingSettlementsLogic } from './partnerBillingSettlementsLogic'
import { PartnerBillingStatusTag } from './PartnerBillingStatusTag'

export function PartnerBillingSettlements({ applicationId }: PartnerBillingLogicProps): JSX.Element {
    const logic = partnerBillingSettlementsLogic({ applicationId })
    const { settlements, settlementsLoading, settlementsError, settlementsPage } = useValues(logic)
    const { setSettlementsPage, openSettlement, loadPartnerBillingSettlements } = useActions(logic)

    return (
        <section className="flex flex-col gap-4">
            <div>
                <h3 className="text-base font-semibold mb-1">Settlements</h3>
                <p className="text-secondary text-sm mb-0">
                    A settlement is one charge to your payment method that pays the invoices of every organization you
                    pay for.
                </p>
            </div>
            {settlementsError && !settlementsLoading ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => loadPartnerBillingSettlements(),
                        'data-attr': 'partner-billing-reload-settlements',
                    }}
                >
                    {settlementsError}
                </LemonBanner>
            ) : (
                <LemonTable
                    dataSource={settlements?.results ?? []}
                    loading={settlementsLoading}
                    rowKey="settlement_id"
                    nouns={['settlement', 'settlements']}
                    emptyState="No settlements yet. They appear here once PostHog charges you for your organizations' invoices."
                    pagination={partnerBillingTablePagination(settlementsPage, settlements?.count, setSettlementsPage)}
                    columns={[
                        {
                            title: 'Period',
                            key: 'period',
                            render: (_, settlement) =>
                                formatBillingPeriod(settlement.period_start, settlement.period_end),
                        },
                        {
                            title: 'Amount',
                            key: 'amount',
                            align: 'right',
                            render: (_, settlement) =>
                                settlement.amount_cents !== undefined
                                    ? formatAmountCents(settlement.amount_cents, settlement.currency)
                                    : null,
                        },
                        {
                            title: 'Status',
                            key: 'status',
                            render: (_, settlement) =>
                                settlement.status ? <PartnerBillingStatusTag status={settlement.status} /> : null,
                        },
                        {
                            title: 'Charge',
                            key: 'charge',
                            render: (_, settlement) => formatSettlementCharge(settlement),
                        },
                        {
                            key: 'actions',
                            render: (_, settlement) => (
                                <div className="flex flex-wrap justify-end gap-1">
                                    {isRetryableSettlement(settlement) && (
                                        <PartnerBillingRetryChargeButton
                                            applicationId={applicationId}
                                            settlement={settlement}
                                        />
                                    )}
                                    <LemonButton
                                        size="small"
                                        type="secondary"
                                        onClick={() => openSettlement(settlement.settlement_id)}
                                        data-attr="partner-billing-open-settlement"
                                    >
                                        Details
                                    </LemonButton>
                                </div>
                            ),
                        },
                    ]}
                />
            )}
            <PartnerBillingSettlementModal applicationId={applicationId} />
        </section>
    )
}
