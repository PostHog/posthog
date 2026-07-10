import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'

import { BillingInvoiceItemRow, BillingProductV2AddonType } from '~/types'

/**
 * Confirmation shown before charging for a fresh flat-rate add-on purchase (e.g. adding Scale).
 * Sibling of ConfirmUpgradeModal, which covers switching one platform add-on for another; this
 * covers adding an add-on when there is nothing to switch from. Without it, clicking "Add" with a
 * card on file charged immediately with no summary of what was about to be billed.
 */
export function ConfirmPurchaseModal({ product }: { product: BillingProductV2AddonType }): JSX.Element | null {
    const { billing } = useValues(billingLogic)
    const { currentAndUpgradePlans, confirmPurchaseModalOpen, proratedAmount, billingProductLoading } = useValues(
        billingProductLogic({ product })
    )
    const { hideConfirmPurchaseModal, confirmProductPurchase } = useActions(billingProductLogic({ product }))

    const isLoading = billingProductLoading === product.type

    const targetPlan = currentAndUpgradePlans?.upgradePlan
    const availableCreditBalance = billing?.discount_amount_usd ? parseFloat(billing.discount_amount_usd) : 0
    const appliedBalance = Math.min(proratedAmount, availableCreditBalance)
    const amountDue = Math.max(0, proratedAmount - appliedBalance)

    const periodEnd = billing?.billing_period?.current_period_end
    const remainingPeriodFormatted = periodEnd
        ? `${dayjs().format('MMM D')} - ${periodEnd.format('MMM D, YYYY')}`
        : undefined

    if (!confirmPurchaseModalOpen || !targetPlan) {
        return null
    }

    const rows: BillingInvoiceItemRow[] = [
        {
            description: `Remaining time on ${product.name}`,
            dateRange: remainingPeriodFormatted,
            amount: `$${proratedAmount.toFixed(2)}`,
        },
    ]

    if (appliedBalance > 0) {
        rows.push({
            description: 'Applied balance',
            amount: `-$${appliedBalance.toFixed(2)}`,
        })
    }

    rows.push({
        description: 'Amount due today',
        amount: `$${amountDue.toFixed(2)}`,
        isBold: true,
    })

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

    return (
        <LemonModal
            onClose={hideConfirmPurchaseModal}
            isOpen={confirmPurchaseModalOpen}
            closable={!isLoading}
            title={`Ready to subscribe to ${targetPlan.name}?`}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={hideConfirmPurchaseModal}
                        disabledReason={isLoading ? 'Purchase in progress, do not close this modal' : ''}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={confirmProductPurchase} loading={isLoading}>
                        Confirm
                    </LemonButton>
                </>
            }
        >
            <div className="max-w-140">
                <p>
                    You'll get access to all {product.name} features right away. ${amountDue.toFixed(2)} will be charged
                    now for the remaining period until {billing?.billing_period?.current_period_end?.format('MMM D')},
                    and ${targetPlan.unit_amount_usd} every {targetPlan.unit} thereafter.
                </p>
                <LemonTable dataSource={rows} columns={columns} className="mt-4" uppercaseHeader={false} />
            </div>
        </LemonModal>
    )
}
