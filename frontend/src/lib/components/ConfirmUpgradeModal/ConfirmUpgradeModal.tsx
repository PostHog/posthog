import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonModal, Tooltip } from '@posthog/lemon-ui'

import { getProration } from 'scenes/billing/billing-utils'
import { billingLogic } from 'scenes/billing/billingLogic'

import { confirmUpgradeModalLogic } from './confirmUpgradeModalLogic'

export function ConfirmUpgradeModal(): JSX.Element {
    const { upgradePlan } = useValues(confirmUpgradeModalLogic)
    const { timeRemainingInSeconds, timeTotalInSeconds, billing } = useValues(billingLogic)
    const { hideConfirmUpgradeModal, confirm, cancel } = useActions(confirmUpgradeModalLogic)

    const { prorationAmount, isProrated } = useMemo(
        () =>
            getProration({
                timeRemainingInSeconds,
                timeTotalInSeconds,
                amountUsd: upgradePlan?.unit_amount_usd,
                hasActiveSubscription: billing?.has_active_subscription,
            }),
        [billing?.has_active_subscription, upgradePlan, timeRemainingInSeconds, timeTotalInSeconds]
    )

    return (
        <LemonModal
            onClose={hideConfirmUpgradeModal}
            isOpen={!!upgradePlan}
            closable={false}
            title={`Ready to subscribe to the ${upgradePlan?.name}?`}
            footer={
                <>
                    <LemonButton type="secondary" onClick={() => cancel()}>
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" onClick={() => confirm()}>
                        Sign me up
                    </LemonButton>
                </>
            }
        >
            <div className="max-w-140">
                <p>
                    Woo! You're gonna love the {upgradePlan?.name}. We're just confirming that this is a $
                    {Number(upgradePlan?.unit_amount_usd)} / {upgradePlan?.unit} subscription.{' '}
                    {isProrated
                        ? `The first payment will be prorated to ~$${prorationAmount} and it will be charged immediately.`
                        : 'The first payment will be charged immediately.'}
                </p>
                {upgradePlan && upgradePlan?.features?.length > 1 && (
                    <div>
                        <p className="ml-0 mb-2 max-w-200">Here are the features included:</p>
                        <div className="grid grid-cols-2 gap-x-4">
                            {upgradePlan?.features.map((feature, index) => (
                                <div className="flex gap-x-2 items-center mb-2" key={'addon-features-' + index}>
                                    <IconCheckCircle className="text-success" />
                                    <Tooltip key={feature.key} title={feature.description}>
                                        <b>
                                            {feature.name}
                                            {feature.note ? ': ' + feature.note : ''}
                                        </b>
                                    </Tooltip>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
