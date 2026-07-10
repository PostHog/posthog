import { LemonButton, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { BillingInvoiceItemRow, BillingPlanType } from '~/types'

/**
 * Presentational confirmation dialog shared by ConfirmUpgradeModal (switching one platform add-on
 * for another) and ConfirmPurchaseModal (adding an add-on from scratch). It owns the modal shell,
 * the invoice-preview table, and the charge copy; each caller passes in the line-item rows and the
 * confirm/cancel actions that differ between the two flows.
 */
export interface ConfirmAddonChargeModalProps {
    isOpen: boolean
    /** Plan being subscribed to — drives the title and the recurring-charge copy. */
    targetPlan: BillingPlanType
    /** Add-on product name, e.g. "Scale". */
    productName: string
    isLoading: boolean
    /** Invoice line items to preview; the caller decides which rows the flow needs. */
    rows: BillingInvoiceItemRow[]
    /** Amount charged today, used in the summary sentence. */
    amountDue: number
    /** End of the current billing period, e.g. "Jul 31" — omitted if the period isn't loaded. */
    periodEndLabel?: string
    onCancel: () => void
    onConfirm: () => void
}

const columns: LemonTableColumns<BillingInvoiceItemRow> = [
    {
        title: 'Description',
        dataIndex: 'description',
        render: (_, row) => (
            <div className={`py-1 ${row.isBold ? 'font-bold' : 'font-medium'}`}>
                <div>{row.description}</div>
                {row.dateRange && <div className="text-muted text-xs">{row.dateRange}</div>}
            </div>
        ),
    },
    {
        title: 'Amount',
        dataIndex: 'amount',
        align: 'right',
        render: (_, row) => <div className={`py-1 ${row.isBold ? 'font-bold' : ''}`}>{row.amount}</div>,
    },
]

export function ConfirmAddonChargeModal({
    isOpen,
    targetPlan,
    productName,
    isLoading,
    rows,
    amountDue,
    periodEndLabel,
    onCancel,
    onConfirm,
}: ConfirmAddonChargeModalProps): JSX.Element {
    return (
        <LemonModal
            onClose={onCancel}
            isOpen={isOpen}
            closable={false}
            title={`Ready to subscribe to ${targetPlan.name}?`}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={onCancel}
                        disabledReason={isLoading ? 'Subscription update in progress, do not close this modal' : ''}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={onConfirm} loading={isLoading}>
                        Confirm
                    </LemonButton>
                </>
            }
        >
            <div className="max-w-140">
                <p>
                    You'll get access to all {productName} features right away. ${amountDue.toFixed(2)} will be charged
                    now for the remaining period until {periodEndLabel}, and ${targetPlan.unit_amount_usd} every{' '}
                    {targetPlan.unit} thereafter.
                </p>
                <LemonTable dataSource={rows} columns={columns} className="mt-4" uppercaseHeader={false} />
            </div>
        </LemonModal>
    )
}
