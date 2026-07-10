import { useActions, useValues } from 'kea'

import { dayjs } from 'lib/dayjs'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'

import { BillingInvoiceItemRow, BillingProductV2AddonType } from '~/types'

import { ConfirmAddonChargeModal } from './ConfirmAddonChargeModal'

/**
 * Confirmation shown before switching from one platform add-on to another (e.g. Boost → Scale).
 * The prorated charge is offset by the unused time on the current add-on; ConfirmPurchaseModal is
 * the sibling that covers adding an add-on when there is nothing to switch from.
 */
export function ConfirmUpgradeModal({ product }: { product: BillingProductV2AddonType }): JSX.Element | null {
    const { currentPlatformAddon, unusedPlatformAddonAmount, switchPlanLoading, billing } = useValues(billingLogic)
    const { currentAndUpgradePlans, confirmUpgradeModalOpen, proratedAmount } = useValues(
        billingProductLogic({ product })
    )
    const { hideConfirmUpgradeModal, confirmProductUpgrade } = useActions(billingProductLogic({ product }))

    const targetPlan = currentAndUpgradePlans?.upgradePlan
    const amountDueBeforeCredits = Math.max(0, proratedAmount - unusedPlatformAddonAmount)
    const availableCreditBalance = billing?.discount_amount_usd ? parseFloat(billing.discount_amount_usd) : 0
    const appliedBalance = Math.min(amountDueBeforeCredits, availableCreditBalance)
    const amountDue = Math.max(0, amountDueBeforeCredits - appliedBalance)

    const periodEnd = billing?.billing_period?.current_period_end

    if (!confirmUpgradeModalOpen || !targetPlan || !currentPlatformAddon) {
        return null
    }

    const remainingPeriodFormatted = periodEnd
        ? `${dayjs().format('MMM D')} - ${periodEnd.format('MMM D, YYYY')}`
        : undefined

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
            isOpen={confirmUpgradeModalOpen}
            targetPlan={targetPlan}
            productName={product.name}
            isLoading={switchPlanLoading === product.type}
            rows={rows}
            amountDue={amountDue}
            periodEndLabel={periodEnd?.format('MMM D')}
            onCancel={hideConfirmUpgradeModal}
            onConfirm={confirmProductUpgrade}
        />
    )
}
