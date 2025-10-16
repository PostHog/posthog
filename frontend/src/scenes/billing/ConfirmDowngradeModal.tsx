import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonTable, LemonTableColumns, Link } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { dayjs } from 'lib/dayjs'

import { BillingInvoiceItemRow, BillingProductV2AddonType } from '~/types'

import { AddonFeatureLossNotice } from './AddonFeatureLossNotice'
import { billingLogic } from './billingLogic'
import { billingProductLogic } from './billingProductLogic'

export function ConfirmDowngradeModal({ product }: { product: BillingProductV2AddonType }): JSX.Element | null {
    const { currentPlatformAddon, unusedPlatformAddonAmount, switchPlanLoading, billing } = useValues(billingLogic)
    const { currentAndUpgradePlans, confirmDowngradeModalOpen, proratedAmount } = useValues(
        billingProductLogic({ product })
    )
    const { hideConfirmDowngradeModal, confirmProductDowngrade } = useActions(billingProductLogic({ product }))
    const { openSupportForm } = useActions(supportLogic)

    const isLoading = switchPlanLoading === product.type

    const targetPlan = currentAndUpgradePlans?.upgradePlan
    const fullMonthlyPrice = parseFloat(String(targetPlan?.unit_amount_usd || '0'))
    const nextInvoiceEstimate = Math.max(0, fullMonthlyPrice + proratedAmount - unusedPlatformAddonAmount)
    const creditCoversNextInvoice = unusedPlatformAddonAmount > proratedAmount + fullMonthlyPrice

    const periodEnd = billing?.billing_period?.current_period_end
    const remainingPeriodFormatted = periodEnd
        ? `${dayjs().format('MMM D')} - ${periodEnd.format('MMM D, YYYY')}`
        : undefined

    if (!confirmDowngradeModalOpen || !targetPlan || !currentPlatformAddon) {
        return null
    }

    const rows: BillingInvoiceItemRow[] = [
        {
            description: `Credit for unused time on ${currentPlatformAddon.name}`,
            dateRange: remainingPeriodFormatted,
            amount: `-$${unusedPlatformAddonAmount.toFixed(2)}`,
        },
        {
            description: `Remaining time on ${product.name}`,
            dateRange: remainingPeriodFormatted,
            amount: `$${proratedAmount.toFixed(2)}`,
        },
        {
            description: `${product.name} subscription`,
            dateRange: periodEnd ? `From ${periodEnd.format('MMM D, YYYY')}` : undefined,
            amount: `$${fullMonthlyPrice.toFixed(2)}`,
        },
        {
            description: `Estimated next invoice for ${product.name}`,
            amount: `$${nextInvoiceEstimate.toFixed(2)}`,
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
            onClose={hideConfirmDowngradeModal}
            isOpen={confirmDowngradeModalOpen}
            closable={false}
            title={`Downgrade to ${targetPlan.name}?`}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={hideConfirmDowngradeModal}
                        disabledReason={isLoading ? 'Subscription update in progress, do not close this modal' : ''}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={confirmProductDowngrade} loading={isLoading}>
                        Confirm
                    </LemonButton>
                </>
            }
        >
            <div className="max-w-140">
                <p>
                    You'll lose access to {currentPlatformAddon.name} features immediately. We'll apply credit for
                    unused time to your next invoice(s).
                </p>

                <AddonFeatureLossNotice product={currentPlatformAddon} />

                <LemonTable dataSource={rows} columns={columns} className="mt-4" uppercaseHeader={false} />

                {creditCoversNextInvoice && (
                    <div className="mt-2 text-sm">
                        Remaining credit $
                        {Math.max(0, unusedPlatformAddonAmount - proratedAmount - fullMonthlyPrice).toFixed(2)} will
                        apply to other usage-based charges or roll over to future invoices.{' '}
                        <Link
                            onClick={() => {
                                hideConfirmDowngradeModal()
                                openSupportForm({ target_area: 'billing' })
                            }}
                        >
                            Request a refund instead.
                        </Link>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
