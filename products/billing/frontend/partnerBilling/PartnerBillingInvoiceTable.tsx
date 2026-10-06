import { useValues } from 'kea'

import { LemonButton, LemonTable, LemonTableColumn, LemonTableColumns, PaginationManual } from '@posthog/lemon-ui'

import type { PartnerPayerSettlementInvoiceApi } from '../generated/api.schemas'
import { formatAmountCents, formatBillingPeriod } from './partnerBillingFormat'
import type { PartnerBillingLogicProps } from './partnerBillingLogic'
import { partnerBillingOrganizationsLogic } from './partnerBillingOrganizationsLogic'
import { PartnerBillingStatusTag } from './PartnerBillingStatusTag'

interface PartnerBillingInvoiceTableProps extends PartnerBillingLogicProps {
    invoices: PartnerPayerSettlementInvoiceApi[]
    loading: boolean
    emptyState: string
    pagination?: PaginationManual
    showCharged?: boolean
    chargedColumnTitle?: string
}

const CHARGED_COLUMN: LemonTableColumn<
    PartnerPayerSettlementInvoiceApi,
    keyof PartnerPayerSettlementInvoiceApi | undefined
> = {
    title: 'Charged',
    key: 'charged_cents',
    align: 'right',
    render: (_, invoice) =>
        invoice.charged_cents !== undefined ? formatAmountCents(invoice.charged_cents, invoice.currency) : null,
}

export function PartnerBillingInvoiceTable({
    applicationId,
    invoices,
    loading,
    emptyState,
    pagination,
    showCharged = false,
    chargedColumnTitle = 'Charged',
}: PartnerBillingInvoiceTableProps): JSX.Element {
    const { organizationNames } = useValues(partnerBillingOrganizationsLogic({ applicationId }))

    const columns: LemonTableColumns<PartnerPayerSettlementInvoiceApi> = [
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
            title: 'Amount due',
            key: 'amount',
            align: 'right',
            render: (_, invoice) =>
                invoice.amount_cents === null ? (
                    <span className="text-secondary">Not recorded yet</span>
                ) : invoice.amount_cents !== undefined ? (
                    formatAmountCents(invoice.amount_cents, invoice.currency)
                ) : null,
        },
        ...(showCharged ? [{ ...CHARGED_COLUMN, title: chargedColumnTitle }] : []),
        {
            title: 'Status',
            key: 'status',
            render: (_, invoice) => (invoice.status ? <PartnerBillingStatusTag status={invoice.status} /> : null),
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
    ]

    return (
        <LemonTable
            dataSource={invoices}
            loading={loading}
            rowKey="invoice_id"
            nouns={['invoice', 'invoices']}
            emptyState={emptyState}
            pagination={pagination}
            columns={columns}
        />
    )
}
