import { useValues } from 'kea'

import { LemonButton, LemonTable, PaginationManual } from '@posthog/lemon-ui'

import type { PartnerPayerInvoiceApi } from '../generated/api.schemas'
import { formatAmountCents, formatBillingPeriod } from './partnerBillingFormat'
import type { PartnerBillingLogicProps } from './partnerBillingLogic'
import { partnerBillingOrganizationsLogic } from './partnerBillingOrganizationsLogic'
import { PartnerBillingStatusTag } from './PartnerBillingStatusTag'

interface PartnerBillingInvoiceTableProps extends PartnerBillingLogicProps {
    invoices: PartnerPayerInvoiceApi[]
    loading: boolean
    emptyState: string
    pagination?: PaginationManual
}

export function PartnerBillingInvoiceTable({
    applicationId,
    invoices,
    loading,
    emptyState,
    pagination,
}: PartnerBillingInvoiceTableProps): JSX.Element {
    const { organizationNames } = useValues(partnerBillingOrganizationsLogic({ applicationId }))

    return (
        <LemonTable
            dataSource={invoices}
            loading={loading}
            rowKey="invoice_id"
            nouns={['invoice', 'invoices']}
            emptyState={emptyState}
            pagination={pagination}
            columns={[
                {
                    title: 'Organization',
                    key: 'organization',
                    render: (_, invoice) =>
                        invoice.organization_id
                            ? (organizationNames[invoice.organization_id] ?? (
                                  <span className="font-mono text-xs break-all">{invoice.organization_id}</span>
                              ))
                            : null,
                },
                {
                    title: 'Period',
                    key: 'period',
                    render: (_, invoice) => formatBillingPeriod(invoice.period_start, invoice.period_end),
                },
                {
                    title: 'Amount',
                    key: 'amount',
                    align: 'right',
                    render: (_, invoice) =>
                        invoice.amount_cents !== undefined
                            ? formatAmountCents(invoice.amount_cents, invoice.currency)
                            : null,
                },
                {
                    title: 'Status',
                    key: 'status',
                    render: (_, invoice) =>
                        invoice.status ? <PartnerBillingStatusTag status={invoice.status} /> : null,
                },
                {
                    key: 'pdf',
                    width: 0,
                    render: (_, invoice) =>
                        invoice.pdf_url ? (
                            <LemonButton
                                size="small"
                                type="secondary"
                                to={invoice.pdf_url}
                                targetBlank
                                disableClientSideRouting
                                data-attr="partner-billing-invoice-pdf"
                            >
                                PDF
                            </LemonButton>
                        ) : null,
                },
            ]}
        />
    )
}
