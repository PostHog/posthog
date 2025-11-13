import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'

import { BillingInvoiceItemRow, BillingProductV2AddonType } from '~/types'

export function ConfirmUpgradeModal({ product }: { product: BillingProductV2AddonType }): JSX.Element | null {
    const { currentPlatformAddon, unusedPlatformAddonAmount, switchPlanLoading, billing } = useValues(billingLogic)
    const { currentAndUpgradePlans, confirmUpgradeModalOpen, proratedAmount } = useValues(
        billingProductLogic({ product })
    )
    const { hideConfirmUpgradeModal, confirmProductUpgrade } = useActions(billingProductLogic({ product }))

    const isLoading = switchPlanLoading === product.type

    const targetPlan = currentAndUpgradePlans?.upgradePlan
    const amountDue = Math.max(0, proratedAmount - unusedPlatformAddonAmount)

    const periodEnd = billing?.billing_period?.current_period_end
    const remainingPeriodFormatted = periodEnd
        ? `${dayjs().format('MMM D')} - ${periodEnd.format('MMM D, YYYY')}`
        : undefined

    if (!confirmUpgradeModalOpen || !targetPlan || !currentPlatformAddon) {
        return null
    }

    const rows: BillingInvoiceItemRow[] = [
        {
            description: `Remaining time on ${product.name}`,
            dateRange: remainingPeriodFormatted,
            amount: `$${proratedAmount.toFixed(2)}`,
        },
        {
            description: `Unused time on ${currentPlatformAddon.name}`,
            dateRange: remainingPeriodFormatted,
            amount: `-$${unusedPlatformAddonAmount.toFixed(2)}`,
        },
        {
            description: 'Amount due today',
            amount: `$${amountDue.toFixed(2)}`,
            isBold: true,
        },
    ]

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
            onClose={hideConfirmUpgradeModal}
            isOpen={confirmUpgradeModalOpen}
            closable={false}
            title={`Ready to subscribe to ${targetPlan.name}?`}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={hideConfirmUpgradeModal}
                        disabledReason={isLoading ? 'Subscription update in progress, do not close this modal' : ''}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={confirmProductUpgrade} loading={isLoading}>
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
