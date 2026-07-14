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
    const { currentAndUpgradePlans, confirmUpgradeModalOpen, proratedAmount, appliedCreditBalance, amountDueToday } =
        useValues(billingProductLogic({ product }))
    const { hideConfirmUpgradeModal, confirmProductUpgrade } = useActions(billingProductLogic({ product }))

    const targetPlan = currentAndUpgradePlans?.upgradePlan
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

    if (appliedCreditBalance > 0) {
        rows.push({
            description: 'Applied balance',
            amount: `-$${appliedCreditBalance.toFixed(2)}`,
        })
    }

    rows.push({
        description: 'Amount due today',
        amount: `$${amountDueToday.toFixed(2)}`,
        isBold: true,
    })

    return (
        <ConfirmAddonChargeModal
            isOpen={confirmUpgradeModalOpen}
            targetPlan={targetPlan}
            productName={product.name}
            isLoading={switchPlanLoading === product.type}
            rows={rows}
            amountDue={amountDueToday}
            periodEndLabel={periodEnd?.format('MMM D')}
            onCancel={hideConfirmUpgradeModal}
            onConfirm={confirmProductUpgrade}
        />
    )
}
