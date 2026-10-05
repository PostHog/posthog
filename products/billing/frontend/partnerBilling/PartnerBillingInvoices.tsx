import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSelect, LemonSnack } from '@posthog/lemon-ui'

import { PARTNER_BILLING_INVOICES_ELEMENT_ID, partnerBillingInvoicesLogic } from './partnerBillingInvoicesLogic'
import { PartnerBillingInvoiceTable } from './PartnerBillingInvoiceTable'
import type { PartnerBillingLogicProps } from './partnerBillingLogic'
import { partnerBillingTablePagination } from './partnerBillingPagination'

const INVOICE_STATUS_OPTIONS: { value: string | null; label: string }[] = [
    { value: null, label: 'All statuses' },
    { value: 'draft', label: 'Draft' },
    { value: 'open', label: 'Open' },
    { value: 'paid', label: 'Paid' },
    { value: 'uncollectible', label: 'Uncollectible' },
    { value: 'void', label: 'Void' },
]

export function PartnerBillingInvoices({ applicationId }: PartnerBillingLogicProps): JSX.Element {
    const logic = partnerBillingInvoicesLogic({ applicationId })
    const { invoices, invoicesLoading, invoicesError, invoicesPage, invoiceStatusFilter, invoiceOrganizationFilter } =
        useValues(logic)
    const { setInvoicesPage, setInvoiceStatusFilter, setInvoiceOrganizationFilter, loadPartnerBillingInvoices } =
        useActions(logic)

    return (
        <section id={PARTNER_BILLING_INVOICES_ELEMENT_ID} className="flex flex-col gap-4 scroll-mt-16">
            <div>
                <h3 className="text-base font-semibold mb-1">Invoices</h3>
                <p className="text-secondary text-sm mb-0">
                    Each organization you pay for gets its own invoice. To see one organization's invoices, choose
                    Invoices next to it in the organizations table.
                </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
                <LemonSelect
                    size="small"
                    value={invoiceStatusFilter}
                    onChange={setInvoiceStatusFilter}
                    options={INVOICE_STATUS_OPTIONS}
                    data-attr="partner-billing-invoice-status-filter"
                />
                {invoiceOrganizationFilter && (
                    <LemonSnack
                        onClose={() => setInvoiceOrganizationFilter(null)}
                        title="Show invoices for every organization"
                        data-attr="partner-billing-clear-invoice-organization-filter"
                    >
                        <span>Organization:&nbsp;</span>
                        <span translate="no">{invoiceOrganizationFilter.name}</span>
                    </LemonSnack>
                )}
            </div>
            {invoicesError && !invoicesLoading ? (
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: () => loadPartnerBillingInvoices(),
                        'data-attr': 'partner-billing-reload-invoices',
                    }}
                >
                    {invoicesError}
                </LemonBanner>
            ) : (
                <PartnerBillingInvoiceTable
                    applicationId={applicationId}
                    invoices={invoices?.results ?? []}
                    loading={invoicesLoading}
                    emptyState={
                        invoiceStatusFilter || invoiceOrganizationFilter
                            ? 'No invoices match these filters.'
                            : 'No invoices yet. They appear here once PostHog bills the organizations you pay for.'
                    }
                    pagination={partnerBillingTablePagination(invoicesPage, invoices?.count, setInvoicesPage)}
                />
            )}
        </section>
    )
}
