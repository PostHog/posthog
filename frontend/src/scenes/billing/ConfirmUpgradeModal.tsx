import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { billingLogic } from 'scenes/billing/billingLogic'
import { billingProductLogic } from 'scenes/billing/billingProductLogic'

import { BillingProductV2AddonType } from '~/types'

type PricingRow = {
    description: string
    dateRange?: string
    amount: string
    isBold?: boolean
}

export function ConfirmUpgradeModal({ product }: { product: BillingProductV2AddonType }): JSX.Element | null {
    const { currentPlatformAddon, unusedPlatformAddonAmount, switchPlanLoading, billing } = useValues(billingLogic)
    const { currentAndUpgradePlans, confirmUpgradeModalOpen, proratedAmount } = useValues(
        billingProductLogic({ product })
    )
    const { hideConfirmUpgradeModal, confirmProductUpgrade } = useActions(billingProductLogic({ product }))

    const upgradePlan = currentAndUpgradePlans?.upgradePlan
    const amountDue = Math.max(0, (proratedAmount || 0) - (unusedPlatformAddonAmount || 0))
    const isLoading = switchPlanLoading === product.type

    const periodEnd = billing?.billing_period?.current_period_end
    const remainingPeriod = periodEnd ? `${dayjs().format('MMM D')} - ${periodEnd.format('MMM D, YYYY')}` : undefined

    const pricingRows: PricingRow[] = [
        {
            description: `Remaining time on ${product.name}`,
            dateRange: remainingPeriod,
            amount: `$${proratedAmount.toFixed(2)}`,
        },
        {
            description: `Unused time on ${currentPlatformAddon?.name}`,
            dateRange: remainingPeriod,
            amount: `-$${unusedPlatformAddonAmount?.toFixed(2)}`,
        },
        {
            description: 'Amount due today',
            amount: `$${amountDue.toFixed(2)}`,
            isBold: true,
        },
    ]

    if (!confirmUpgradeModalOpen) {
        return null
    }

    const columns: LemonTableColumns<PricingRow> = [
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
            title={upgradePlan?.name ? `Ready to subscribe to ${upgradePlan.name}?` : ''}
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
            {upgradePlan && (
                <div className="max-w-140">
                    <p>
                        You'll get access to all {product.name} features right away. ${amountDue.toFixed(2)} will be
                        charged now for the remaining period until{' '}
                        {billing?.billing_period?.current_period_end?.format('MMM D')}, and $
                        {upgradePlan.unit_amount_usd} per {upgradePlan.unit} thereafter.
                    </p>
                    <LemonTable dataSource={pricingRows} columns={columns} className="mt-4" uppercaseHeader={false} />
                </div>
            )}
        </LemonModal>
    )
}
