import { useActions, useValues } from 'kea'

import { dayjs } from 'lib/dayjs'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'

import { BillingInvoiceItemRow, BillingProductV2AddonType } from '~/types'

import { ConfirmAddonChargeModal } from './ConfirmAddonChargeModal'

/**
 * Confirmation shown before charging for a fresh flat-rate add-on purchase (e.g. adding Scale).
 * Sibling of ConfirmUpgradeModal, which covers switching one platform add-on for another; this
 * covers adding an add-on when there is nothing to switch from. Without it, clicking "Add" with a
 * card on file charged immediately with no summary of what was about to be billed.
 */
export function ConfirmPurchaseModal({
    product,
    onConfirm,
}: {
    product: BillingProductV2AddonType
    // Fired when the user confirms (not when the modal opens), so the caller can start any
    // parent "activating" lock only once a charge is actually happening.
    onConfirm?: () => void
}): JSX.Element | null {
    const { billing } = useValues(billingLogic)
    const { currentAndUpgradePlans, confirmPurchaseModalOpen, proratedAmount, billingProductLoading } = useValues(
        billingProductLogic({ product })
    )
    const { hideConfirmPurchaseModal, confirmProductPurchase } = useActions(billingProductLogic({ product }))

    const targetPlan = currentAndUpgradePlans?.upgradePlan
    const availableCreditBalance = billing?.discount_amount_usd ? parseFloat(billing.discount_amount_usd) : 0
    const appliedBalance = Math.min(proratedAmount, availableCreditBalance)
    const amountDue = Math.max(0, proratedAmount - appliedBalance)

    const periodEnd = billing?.billing_period?.current_period_end

    // Require a loaded billing period: without it proratedAmount falls back to 0, which would
    // misleadingly show "$0.00 due today" for a charge the backend still applies at the full rate.
    if (!confirmPurchaseModalOpen || !targetPlan || !periodEnd) {
        return null
    }

    const remainingPeriodFormatted = `${dayjs().format('MMM D')} - ${periodEnd.format('MMM D, YYYY')}`

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

    return (
        <ConfirmAddonChargeModal
            isOpen={confirmPurchaseModalOpen}
            targetPlan={targetPlan}
            productName={product.name}
            isLoading={billingProductLoading === product.type}
            rows={rows}
            amountDue={amountDue}
            periodEndLabel={periodEnd.format('MMM D')}
            onCancel={hideConfirmPurchaseModal}
            onConfirm={() => {
                onConfirm?.()
                confirmProductPurchase()
            }}
        />
    )
}
